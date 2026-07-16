"""
Nadi Hardware — WebSocket backend server.

Runs on the Raspberry Pi alongside the Next.js frontend (Chromium kiosk).

Sensor responsibilities:
  HC-SR04 ultrasonic → distance measurement (accurate, zero camera CPU load)
  Pi Camera (main)   → 720p JPEG preview + 320×240 resize for YuNet attention

WebSocket message sent to all connected clients every frame:
{
    "type":             "frame",
    "face_detected":    bool,
    "face_count":       int,
    "attention_ok":     bool,       # false → frontend should pause the test
    "attention_reason": str,        # "ok" | "no_face" | "multiple_faces"
                                    #   | "looking_away" | "both_eyes_closed"
                                    #   | "untested_eye_open"
                                    #   | "camera_starting" | "detection_error"
                                    #   | "detector_unavailable"
    "distance":         float,      # screen-to-eye metres (HC-SR04 + offset)
    "raw_distance":     float,      # unfiltered metres (HC-SR04 + offset)
    "confidence":       float,      # 1.0 when ultrasonic active, 0.0 if no reading
    "iris_px":          null,       # always null (ultrasonic handles distance)
    "focal_length_px":  null,       # always null
    "untested_eye_open_events": int,  # cumulative confirmed untested-eye-open events
    "occlusion_confidence_low": bool  # true if any ambiguous eye score this session
}

Calibration message received from frontend (kept for backward compat, ignored):
{
    "type":    "calibrate",
    "ipd_mm":  float
}
"""

import asyncio
import json
import logging
import time
from typing import Optional, Set

import cv2  # for JPEG encoding of preview frames

import websockets
from websockets.server import WebSocketServerProtocol

from camera import PiCamera
from face_detection import FaceDetector
from ultrasonic import UltrasonicSensor
from attention.pipeline import AttentionPipeline
from attention.head_pose import HeadPoseEstimator
from attention.eye_closure import MockEyeClosureDetector
from constants import WS_HOST, WS_PORT, sensor_to_eye_distance

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------

connected_clients: Set[WebSocketServerProtocol] = set()
# Module-level pipeline reference so handle_client can call set_eye_tested().
# Set in main() after the pipeline is created.
_pipeline: Optional[AttentionPipeline] = None

# ---------------------------------------------------------------------------
# WebSocket handler
# ---------------------------------------------------------------------------


async def handle_client(websocket: WebSocketServerProtocol) -> None:
    connected_clients.add(websocket)
    client_addr = websocket.remote_address
    logger.info("Client connected: %s  (total: %d)", client_addr, len(connected_clients))

    # Reset to binocular mode on every (re)connect so stale test-mode state
    # from a previous session never leaks into a new one.
    if _pipeline is not None:
        _pipeline.reset_eye_tested()

    try:
        async for raw_msg in websocket:
            try:
                msg = json.loads(raw_msg)
            except json.JSONDecodeError:
                continue

            # IPD / focal-length calibration messages are kept for backward
            # compat with the frontend but are no longer used — distance now
            # comes from the HC-SR04 ultrasonic sensor.
            if msg.get("type") in ("calibrate", "set_focal_length"):
                logger.debug("Received legacy calibration message (ignored): %s", msg)

            # Objective 2: monocular test mode — frontend sends eye being tested
            elif msg.get("type") == "set_test_mode":
                eye = str(msg.get("eye", "OU"))
                if eye not in ("OD", "OS", "OU"):
                    logger.warning("set_test_mode: invalid eye value '%s' — ignoring", eye)
                elif _pipeline is not None:
                    _pipeline.set_eye_tested(eye)
                    logger.info("Test mode set: eye_tested=%s", eye)

    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        connected_clients.discard(websocket)
        logger.info(
            "Client disconnected: %s  (total: %d)", client_addr, len(connected_clients)
        )


# ---------------------------------------------------------------------------
# Main camera + sensor loop
# ---------------------------------------------------------------------------


async def camera_loop(
    camera: PiCamera,
    pipeline: Optional[AttentionPipeline],
    ultrasonic: UltrasonicSensor,
) -> None:
    loop = asyncio.get_event_loop()
    target_interval = 1.0 / 30   # target ~30 fps broadcast rate
    _preview_counter = 0
    PREVIEW_SKIP = 3              # JPEG preview every 3 frames (~10 fps) to save bandwidth

    while True:
        t0 = time.monotonic()

        # ---- Grab detection frame (320×240 from camera) ----
        detect_frame = await loop.run_in_executor(None, camera.grab_detect_frame)

        if detect_frame is None:
            # Camera still warming up — state is unknown; report honestly.
            distance_m     = sensor_to_eye_distance(ultrasonic.distance_m)
            raw_distance_m = sensor_to_eye_distance(ultrasonic.raw_distance_m)
            no_cam_msg = json.dumps({
                "type": "frame",
                "face_detected": False,
                "face_count": 0,
                "attention_ok": False,
                "attention_reason": "camera_starting",
                "distance": round(distance_m, 4),
                "raw_distance": round(raw_distance_m, 4),
                "confidence": round(1.0 if ultrasonic.is_sensor_active else 0.0, 4),
                "iris_px": None,
                "focal_length_px": None,
                "untested_eye_open_events": 0,
                "occlusion_confidence_low": False,
            })
            if connected_clients:
                await asyncio.gather(
                    *[client.send(no_cam_msg) for client in connected_clients.copy()],
                    return_exceptions=True,
                )
            await asyncio.sleep(0.05)
            continue

        # ---- Attention detection (CPU-bound → executor) ----
        if pipeline is not None:
            detection = await loop.run_in_executor(None, pipeline.process, detect_frame)
        else:
            # YuNet failed to load at startup — run without face detection
            detection = {"face_detected": False, "face_count": 0,
                         "attention_ok": False, "attention_reason": "detector_unavailable",
                         "untested_eye_open_events": 0, "occlusion_confidence_low": False}

        # Defensive guard: if face_detection.py returns an unexpected format
        # (e.g. old version without attention_ok), log a warning and continue
        # safely instead of crashing the whole server.
        if not isinstance(detection, dict) or "attention_ok" not in detection:
            logger.warning(
                "detector.process() returned unexpected format: %s — "
                "check face_detection.py version. Treating as face present.",
                type(detection).__name__,
            )
            detection = {
                "face_detected": detection.get("face_detected", False) if isinstance(detection, dict) else False,
                "face_count":    detection.get("face_count", 0)        if isinstance(detection, dict) else 0,
                "attention_ok":     False,              # state is unknown — report honestly
                "attention_reason": "detection_error",
                "untested_eye_open_events": 0,
                "occlusion_confidence_low": False,
            }

        # ---- Distance from HC-SR04 (non-blocking property read) ----
        distance_m     = sensor_to_eye_distance(ultrasonic.distance_m)
        raw_distance_m = sensor_to_eye_distance(ultrasonic.raw_distance_m)
        # confidence is 1.0 ONLY when sensor is wired and returning valid readings.
        # When sensor is unplugged/out-of-range, is_sensor_active=False and
        # distance_m=0.0, so confidence=0.0 — frontend correctly blocks the test.
        confidence     = 1.0 if ultrasonic.is_sensor_active else 0.0

        # ---- Build WebSocket JSON message ----
        message = json.dumps({
            "type":             "frame",
            "face_detected":    detection["face_detected"],
            "face_count":       detection["face_count"],
            "attention_ok":     detection["attention_ok"],
            "attention_reason": detection["attention_reason"],
            "distance":         round(distance_m, 4),
            "raw_distance":     round(raw_distance_m, 4),
            "confidence":       round(confidence, 4),
            "iris_px":          None,
            "focal_length_px":  None,
            "untested_eye_open_events": detection.get("untested_eye_open_events", 0),
            "occlusion_confidence_low": detection.get("occlusion_confidence_low", False),
        })

        if connected_clients:
            await asyncio.gather(
                *[client.send(message) for client in connected_clients.copy()],
                return_exceptions=True,
            )

        # ---- JPEG preview every PREVIEW_SKIP frames ----
        _preview_counter += 1
        if _preview_counter >= PREVIEW_SKIP and connected_clients:
            _preview_counter = 0
            preview_frame = await loop.run_in_executor(None, camera.grab_frame)
            if preview_frame is not None:
                # Downscale 720p → 640×360 for the WebSocket preview (saves bandwidth)
                ph, pw = preview_frame.shape[0] // 2, preview_frame.shape[1] // 2
                small = cv2.resize(preview_frame, (pw, ph))
                _, jpeg_buf = cv2.imencode(
                    ".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 65]
                )
                jpeg_bytes = jpeg_buf.tobytes()
                await asyncio.gather(
                    *[client.send(jpeg_bytes) for client in connected_clients.copy()],
                    return_exceptions=True,
                )

        # ---- Throttle to target frame rate ----
        elapsed    = time.monotonic() - t0
        sleep_time = target_interval - elapsed
        if sleep_time > 0:
            await asyncio.sleep(sleep_time)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    logger.info("Starting Nadi Hardware backend…")

    # Start ultrasonic sensor (background GPIO thread)
    ultrasonic = UltrasonicSensor()
    ultrasonic.start()
    logger.info("HC-SR04 ultrasonic sensor started")

    # Start camera (720p main stream; detection canvas created by resize in camera.py)
    camera = PiCamera()
    camera.start()
    logger.info(
        "Pi Camera started — %dx%d, detection canvas 320×240",
        camera.width, camera.height,
    )

    loop = asyncio.get_event_loop()

    logger.info("WebSocket server listening on ws://%s:%d", WS_HOST, WS_PORT)
    async with websockets.serve(handle_client, WS_HOST, WS_PORT):

        # Load YuNet in executor so the event loop stays free during model init
        logger.info("Loading YuNet face detector…")
        try:
            detector = await loop.run_in_executor(
                None,
                lambda: FaceDetector(
                    max_num_faces=2,
                    score_threshold=0.6,
                    refine_landmarks=True,
                    min_detection_confidence=0.5,
                    min_tracking_confidence=0.5,
                ),
            )
            logger.info("YuNet loaded — attention monitoring active")
        except Exception as exc:
            logger.error(
                "YuNet detector failed to load: %s\n"
                "  Attention monitoring disabled — test will proceed without face detection.",
                exc,
            )
            detector = None  # camera_loop handles None pipeline gracefully

        # Wrap detector in the unified attention pipeline:
        # face detection (YuNet) → head pose (solvePnP) → eye closure (mock until Obj 1 TFLite)
        if detector is not None:
            pipeline: Optional[AttentionPipeline] = AttentionPipeline(
                detector,
                HeadPoseEstimator(),
                MockEyeClosureDetector(),   # replace with TFLiteEyeClosureDetector once model is selected
            )
            logger.info(
                "Attention pipeline active — face detection + head pose (solvePnP) + "
                "eye closure (MockEyeClosureDetector placeholder)"
            )
        else:
            pipeline = None

        # Expose pipeline to handle_client so it can call set_eye_tested()
        global _pipeline
        _pipeline = pipeline

        camera_task = asyncio.create_task(
            camera_loop(camera, pipeline, ultrasonic)
        )

        try:
            await camera_task
        except asyncio.CancelledError:
            pass
        finally:
            camera.stop()
            if detector is not None:
                detector.close()
            ultrasonic.stop()
            logger.info("Shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
