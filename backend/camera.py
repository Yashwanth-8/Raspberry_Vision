"""
Pi Camera capture using picamera2 (Raspberry Pi OS Bookworm standard).

Two simultaneous streams:
  main  — 1280×720 RGB888  → JPEG preview sent to the frontend browser
  lores — 320×240  YUV420  → resized/converted to BGR for YuNet detection

The split keeps detection fast (320×240 ≈ 8 ms on Pi 4) while the browser
still receives a quality 720p preview frame.

Falls back to a single OpenCV webcam stream (resized for both uses) when
picamera2 is not available (laptop / dev environment).
"""

import threading
from typing import Optional
import numpy as np

try:
    from picamera2 import Picamera2
    PICAMERA2_AVAILABLE = True
except ImportError:
    PICAMERA2_AVAILABLE = False

from constants import (
    CAMERA_WIDTH, CAMERA_HEIGHT, CAMERA_FRAMERATE,
    DETECT_WIDTH, DETECT_HEIGHT,
)


class PiCamera:
    """
    Thread-safe Pi Camera wrapper.

    grab_frame()        → latest 720p BGR frame  (preview)
    grab_detect_frame() → latest 320×240 BGR frame (YuNet input)
    """

    def __init__(
        self,
        width: int = CAMERA_WIDTH,
        height: int = CAMERA_HEIGHT,
        framerate: int = CAMERA_FRAMERATE,
    ) -> None:
        self._width = width
        self._height = height
        self._framerate = framerate
        self._frame: Optional[np.ndarray] = None
        self._detect_frame: Optional[np.ndarray] = None
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._use_picamera2 = PICAMERA2_AVAILABLE

    # ------------------------------------------------------------------
    def start(self) -> None:
        self._running = True
        if self._use_picamera2:
            self._start_picamera2()
        else:
            self._start_opencv()

    # ------------------------------------------------------------------
    def _start_picamera2(self) -> None:
        import cv2  # noqa: F401 — needed for YUV conversion in capture loop
        self._cv2 = cv2

        self._cam = Picamera2()
        config = self._cam.create_preview_configuration(
            main={
                # 720p for the browser preview
                "size": (self._width, self._height),
                # RGB888: libcamera ISP native output — avoids BGR888 colour inversion
                "format": "RGB888",
            },
            lores={
                # Low-res for fast YuNet detection — lores only supports YUV420
                "size": (DETECT_WIDTH, DETECT_HEIGHT),
                "format": "YUV420",
            },
            controls={"FrameRate": self._framerate},
            # 2 buffers = minimum frame-queue depth → lowest end-to-end latency
            buffer_count=2,
        )
        self._cam.configure(config)
        self._cam.start()
        self._thread = threading.Thread(
            target=self._capture_loop_picamera2, daemon=True
        )
        self._thread.start()

    def _capture_loop_picamera2(self) -> None:
        cv2 = self._cv2
        while self._running:
            # Capture both streams atomically from the same camera request
            request = self._cam.capture_request()
            try:
                main_arr  = request.make_array("main")   # (720, 1280, 3) RGB
                lores_arr = request.make_array("lores")  # (360, 320)   YUV420p
            finally:
                request.release()

            # RGB → BGR for OpenCV / browser JPEG encoding
            main_bgr = main_arr[:, :, ::-1].copy()

            # YUV420p → BGR for YuNet (picamera2 lores is I420 layout)
            lores_bgr = cv2.cvtColor(lores_arr, cv2.COLOR_YUV2BGR_I420)

            with self._lock:
                self._frame = main_bgr
                self._detect_frame = lores_bgr

    # ------------------------------------------------------------------
    def _start_opencv(self) -> None:
        import cv2
        self._cv2 = cv2
        self._cap = cv2.VideoCapture(0)
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        self._cap.set(cv2.CAP_PROP_FPS, self._framerate)
        self._thread = threading.Thread(
            target=self._capture_loop_opencv, daemon=True
        )
        self._thread.start()

    def _capture_loop_opencv(self) -> None:
        cv2 = self._cv2
        while self._running:
            ret, frame = self._cap.read()
            if ret:
                detect = cv2.resize(frame, (DETECT_WIDTH, DETECT_HEIGHT))
                with self._lock:
                    self._frame = frame
                    self._detect_frame = detect

    # ------------------------------------------------------------------
    def grab_frame(self) -> Optional[np.ndarray]:
        """Latest full-resolution (720p) BGR frame for the preview stream."""
        with self._lock:
            return self._frame.copy() if self._frame is not None else None

    def grab_detect_frame(self) -> Optional[np.ndarray]:
        """Latest 320×240 BGR frame for YuNet attention detection."""
        with self._lock:
            return self._detect_frame.copy() if self._detect_frame is not None else None

    # ------------------------------------------------------------------
    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        if self._use_picamera2 and hasattr(self, "_cam"):
            self._cam.stop()
        elif hasattr(self, "_cap"):
            self._cap.release()

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

