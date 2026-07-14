"""
Pi Camera capture using picamera2 (Raspberry Pi OS Bookworm standard).

Single main stream: 1280×720 RGB888 for the browser preview.
The detection frame (320×240 BGR) is produced by resizing the main frame
in the capture loop — avoids the YUV420 stride/padding crash on Pi 4.

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
        import cv2
        self._cv2 = cv2

        self._cam = Picamera2()
        config = self._cam.create_preview_configuration(
            main={
                # Single stream: 720p RGB888 for preview.
                # The detect frame is produced by resizing main_bgr in the
                # capture loop — avoids the YUV420 stride/padding issue that
                # would silently kill the capture thread on Pi 4.
                "size": (self._width, self._height),
                "format": "RGB888",
            },
            controls={"FrameRate": self._framerate},
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
            request = self._cam.capture_request()
            try:
                main_arr = request.make_array("main")   # (720, 1280, 3) RGB888
            finally:
                request.release()

            # RGB → BGR for OpenCV
            main_bgr = main_arr[:, :, ::-1].copy()
            # Resize to detection canvas (fast, deterministic, no format issues)
            detect_bgr = cv2.resize(main_bgr, (DETECT_WIDTH, DETECT_HEIGHT))

            with self._lock:
                self._frame = main_bgr
                self._detect_frame = detect_bgr

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

