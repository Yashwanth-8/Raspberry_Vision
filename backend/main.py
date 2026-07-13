"""
Nadi Hardware — WebSocket backend server.

Runs on the Raspberry Pi alongside the Next.js frontend (Chromium kiosk).
Streams real-time face detection and distance data to ws://localhost:8765.

Frame message sent to all connected clients:
{
    "type": "frame",
    "face_detected": bool,
    "face_count": int,
    "distance": float,          # Kalman-filtered, metres
    "raw_distance": float,      # fused but unfiltered
    "confidence": float,        # 0-1
    "iris_px": float | null,    # average iris diameter in pixels (for diagnostics)
    "focal_length_px": float    # focal length used
}

Calibration message received from frontend:
{
    "type": "calibrate",
    "ipd_mm": float             # user's IPD from IPDScreen
}
"""

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
