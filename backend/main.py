"""
Nadi Hardware — WebSocket backend server.

Runs on the Raspberry Pi alongside the Next.js frontend (Chromium kiosk).

Sensor responsibilities:
  HC-SR04 ultrasonic → distance measurement (accurate, zero camera CPU load)
  Pi Camera (lores)  → attention monitoring via YuNet (is user looking?)
  Pi Camera (main)   → 720p JPEG preview stream to the browser

WebSocket message sent to all connected clients every frame:
{
    "type":             "frame",
    "face_detected":    bool,
    "face_count":       int,
    "attention_ok":     bool,       # false → frontend should pause the test
    "attention_reason": str,        # "ok" | "no_face" | "multiple_faces"
                                    #   | "not_centred" | "looking_away"
    "distance":         float,      # Kalman-filtered metres (from ultrasonic)
    "raw_distance":     float,      # unfiltered metres
    "confidence":       float,      # 1.0 when ultrasonic active, 0.0 if no reading
    "iris_px":          null,       # always null (ultrasonic handles distance)
    "focal_length_px":  null        # always null
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
from kalman import KalmanFilter1D
from constants import WS_HOST, WS_PORT

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------

connected_clients: Set[WebSocketServerProtocol] = set()

# ---------------------------------------------------------------------------
# WebSocket handler
# ---------------------------------------------------------------------------


async def handle_client(websocket: WebSocketServerProtocol) -> None:
    connected_clients.add(websocket)
    client_addr = websocket.remote_address
    logger.info("Client connected: %s  (total: %d)", client_addr, len(connected_clients))

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
    detector: FaceDetector,
    ultrasonic: UltrasonicSensor,
) -> None:
    loop = asyncio.get_event_loop()
    target_interval = 1.0 / 30   # target ~30 fps broadcast rate
    _preview_counter = 0
    PREVIEW_SKIP = 3              # JPEG preview every 3 frames (~10 fps) to save bandwidth

    while True:
        t0 = time.monotonic()

        # ---- Grab detection frame (320×240 lores) ----
        detect_frame = await loop.run_in_executor(None, camera.grab_detect_frame)

        if detect_frame is None:
            await asyncio.sleep(0.01)
            continue

        # ---- Attention detection (CPU-bound → executor) ----
        detection = await loop.run_in_executor(None, detector.process, detect_frame)

        # ---- Distance from HC-SR04 (non-blocking property read) ----
        distance_m     = ultrasonic.distance_m
        raw_distance_m = ultrasonic.raw_distance_m
        confidence     = 1.0 if distance_m > 0 else 0.0

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

    # Start camera (dual-stream: 720p preview + 320×240 lores)
    camera = PiCamera()
    camera.start()
    logger.info(
        "Pi Camera started — main %dx%d, lores 320×240",
        camera.width, camera.height,
    )

    loop = asyncio.get_event_loop()

    logger.info("WebSocket server listening on ws://%s:%d", WS_HOST, WS_PORT)
    async with websockets.serve(handle_client, WS_HOST, WS_PORT):

        # Load YuNet in executor so the event loop stays free during model init
        logger.info("Loading YuNet face detector…")
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

        camera_task = asyncio.create_task(
            camera_loop(camera, detector, ultrasonic)
        )

        try:
            await camera_task
        except asyncio.CancelledError:
            pass
        finally:
            camera.stop()
            detector.close()
            ultrasonic.stop()
            logger.info("Shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())


import asyncio
import json
import logging
import time
from typing import Set

import cv2  # for JPEG encoding of preview frames

import websockets
from websockets.server import WebSocketServerProtocol

from camera import PiCamera
from face_detection import FaceDetector
from distance import (
    auto_estimate_focal_length,
    estimate_from_iris,
    estimate_from_ipd,
    estimate_from_face_width,
    fuse_distance_estimates,
)
from kalman import KalmanFilter1D
from constants import WS_HOST, WS_PORT, DEFAULT_IPD_MM, CAMERA_WIDTH, CAMERA_HEIGHT

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared mutable state (safe because asyncio is single-threaded for the WS loop)
# ---------------------------------------------------------------------------

connected_clients: Set[WebSocketServerProtocol] = set()
current_ipd_mm: float = DEFAULT_IPD_MM
focal_length_px: float = auto_estimate_focal_length(CAMERA_WIDTH)

# ---------------------------------------------------------------------------
# WebSocket handler
# ---------------------------------------------------------------------------


async def handle_client(websocket: WebSocketServerProtocol) -> None:
    global current_ipd_mm, focal_length_px

    connected_clients.add(websocket)
    client_addr = websocket.remote_address
    logger.info("Client connected: %s  (total: %d)", client_addr, len(connected_clients))

    try:
        async for raw_msg in websocket:
            try:
                msg = json.loads(raw_msg)
            except json.JSONDecodeError:
                continue

            if msg.get("type") == "calibrate":
                ipd = float(msg.get("ipd_mm", DEFAULT_IPD_MM))
                if 40 <= ipd <= 90:  # sanity bounds
                    current_ipd_mm = ipd
                    logger.info("IPD updated: %.1f mm", current_ipd_mm)

            elif msg.get("type") == "set_focal_length":
                fpx = float(msg.get("focal_length_px", 0))
                if fpx > 0:
                    focal_length_px = fpx
                    logger.info("Focal length updated: %.1f px", focal_length_px)

    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        connected_clients.discard(websocket)
        logger.info("Client disconnected: %s  (total: %d)", client_addr, len(connected_clients))


# ---------------------------------------------------------------------------
# Camera + face-detection loop (runs in executor thread via asyncio)
# ---------------------------------------------------------------------------


async def camera_loop(
    camera: PiCamera,
    detector: FaceDetector,
    kalman: KalmanFilter1D,
) -> None:
    global current_ipd_mm, focal_length_px

    loop = asyncio.get_event_loop()
    target_interval = 1.0 / 30  # aim for ~30 fps broadcasts
    _preview_counter = 0
    PREVIEW_SKIP = 2  # send JPEG preview every 2 frames (~15 fps)

    while True:
        t0 = time.monotonic()

        # Grab latest frame (blocking camera read runs in thread pool)
        frame = await loop.run_in_executor(None, camera.grab_frame)

        if frame is None:
            await asyncio.sleep(0.01)
            continue

        # Face detection (CPU-bound — run in executor so event loop stays free)
        detection = await loop.run_in_executor(
            None, detector.process, frame
        )

        iris_px = None  # type: Optional[float]
        raw_distance = 0.0
        confidence = 0.0
        filtered_distance = 0.0

        if detection["face_detected"] and detection["landmarks"]:
            landmarks = detection["landmarks"]
            fpx = focal_length_px
            w, h = camera.width, camera.height

            estimates = [
                estimate_from_iris(landmarks, fpx, w, h),
                estimate_from_ipd(landmarks, fpx, current_ipd_mm, w, h),
                estimate_from_face_width(landmarks, fpx, w, h),
            ]

            iris_est = estimates[0]
            if iris_est:
                iris_px = iris_est.get("iris_px")

            fused = fuse_distance_estimates(estimates)
            raw_distance = fused["distance"]
            confidence = fused["confidence"]

            if raw_distance > 0:
                filtered_distance = kalman.update(raw_distance)
            else:
                filtered_distance = kalman.estimate
        else:
            # No face — don't update Kalman, but report last estimate
            filtered_distance = kalman.estimate

        # Build message
        message = json.dumps({
            "type": "frame",
            "face_detected": detection["face_detected"],
            "face_count": detection["face_count"],
            "distance": round(filtered_distance, 4),
            "raw_distance": round(raw_distance, 4),
            "confidence": round(confidence, 4),
            "iris_px": round(iris_px, 2) if iris_px is not None else None,
            "focal_length_px": round(focal_length_px, 1),
        })

        # Broadcast JSON data to all connected clients
        if connected_clients:
            await asyncio.gather(
                *[client.send(message) for client in connected_clients.copy()],
                return_exceptions=True,
            )

        # Send JPEG preview frame every PREVIEW_SKIP frames
        _preview_counter += 1
        if _preview_counter >= PREVIEW_SKIP and connected_clients:
            _preview_counter = 0
            ph, pw = frame.shape[0] // 2, frame.shape[1] // 2
            small = cv2.resize(frame, (pw, ph))
            _, jpeg_buf = cv2.imencode('.jpg', small, [cv2.IMWRITE_JPEG_QUALITY, 60])
            jpeg_bytes = jpeg_buf.tobytes()
            await asyncio.gather(
                *[client.send(jpeg_bytes) for client in connected_clients.copy()],
                return_exceptions=True,
            )

        # Throttle to target frame rate
        elapsed = time.monotonic() - t0
        sleep_time = target_interval - elapsed
        if sleep_time > 0:
            await asyncio.sleep(sleep_time)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    logger.info("Starting Nadi Hardware backend...")

    camera = PiCamera()
    camera.start()
    logger.info("Pi Camera started (%dx%d)", camera.width, camera.height)

    loop = asyncio.get_event_loop()

    # Start WebSocket server FIRST so the frontend can connect immediately.
    # MediaPipe initialisation (3–8 s on first run) runs in an executor thread
    # so it never blocks the event loop or the WS handshake.
    logger.info("WebSocket server listening on ws://%s:%d", WS_HOST, WS_PORT)
    async with websockets.serve(handle_client, WS_HOST, WS_PORT):
        logger.info("Loading MediaPipe FaceMesh (may take a few seconds on first run)...")
        detector = await loop.run_in_executor(
            None,
            lambda: FaceDetector(
                max_num_faces=1,
                refine_landmarks=True,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5,
            ),
        )
        logger.info("Face detector (YuNet) loaded")

        kalman = KalmanFilter1D(initial_estimate=2.0, process_noise=0.005, measurement_noise=0.08)

        # Start camera + detection loop as a background task
        camera_task = asyncio.create_task(camera_loop(camera, detector, kalman))

        try:
            await camera_task
        except asyncio.CancelledError:
            pass
        finally:
            camera.stop()
            detector.close()
            logger.info("Shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
