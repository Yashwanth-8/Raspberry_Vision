"""
Pi Camera capture using picamera2 (Raspberry Pi OS Bookworm standard).
Returns BGR numpy frames compatible with MediaPipe / OpenCV.
"""

import threading
from typing import Optional
import numpy as np

try:
    from picamera2 import Picamera2
    PICAMERA2_AVAILABLE = True
except ImportError:
    PICAMERA2_AVAILABLE = False

from constants import CAMERA_WIDTH, CAMERA_HEIGHT, CAMERA_FRAMERATE


class PiCamera:
    """
    Thread-safe Pi Camera wrapper using picamera2.
    Provides grab_frame() which returns the latest BGR frame as numpy array.
    Falls back to OpenCV /dev/video0 if picamera2 is not available (useful for
    testing on a laptop with a USB webcam).
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
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._use_picamera2 = PICAMERA2_AVAILABLE

    def start(self) -> None:
        self._running = True
        if self._use_picamera2:
            self._start_picamera2()
        else:
            self._start_opencv()

    def _start_picamera2(self) -> None:
        self._cam = Picamera2()
        config = self._cam.create_preview_configuration(
            main={
                "size": (self._width, self._height),
                "format": "BGR888",
            },
            controls={"FrameRate": self._framerate},
        )
        self._cam.configure(config)
        self._cam.start()
        self._thread = threading.Thread(target=self._capture_loop_picamera2, daemon=True)
        self._thread.start()

    def _capture_loop_picamera2(self) -> None:
        while self._running:
            frame = self._cam.capture_array()  # returns BGR888 numpy array
            with self._lock:
                self._frame = frame

    def _start_opencv(self) -> None:
        import cv2  # type: ignore
        self._cap = cv2.VideoCapture(0)
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        self._cap.set(cv2.CAP_PROP_FPS, self._framerate)
        self._thread = threading.Thread(target=self._capture_loop_opencv, daemon=True)
        self._thread.start()

    def _capture_loop_opencv(self) -> None:
        while self._running:
            ret, frame = self._cap.read()
            if ret:
                with self._lock:
                    self._frame = frame

    def grab_frame(self) -> Optional[np.ndarray]:
        with self._lock:
            return self._frame.copy() if self._frame is not None else None

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
