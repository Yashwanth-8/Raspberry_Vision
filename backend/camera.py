"""
Pi Camera capture using picamera2 (Raspberry Pi OS Bookworm standard).

Single main stream: 1280×720 XRGB8888 for the browser preview.
XRGB8888 is delivered by picamera2 as BGRX byte order on all Pi Camera
modules — dropping the padding byte gives correct BGR for OpenCV.
The detection frame (320×240 BGR) is produced by resizing the main frame
in the capture loop.

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
                "size": (self._width, self._height),
                # XRGB8888 is the most universally supported format across all
                # Pi Camera modules. picamera2 delivers it as BGRX byte order,
                # so we simply drop the padding channel to get BGR for OpenCV.
                # RGB888 and BGR888 have inconsistent byte-order behaviour across
                # different Pi Camera hardware and libcamera versions.
                "format": "XRGB8888",
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
        import logging
        _log = logging.getLogger(__name__)
        while self._running:
            try:
                request = self._cam.capture_request()
                try:
                    main_arr = request.make_array("main")   # (H, W, 4) in BGRX order
                finally:
                    request.release()

                # Drop the padding byte (X) — remaining channels are B, G, R → correct BGR
                main_bgr = main_arr[:, :, :3].copy()
                # Resize to detection canvas
                detect_bgr = cv2.resize(main_bgr, (DETECT_WIDTH, DETECT_HEIGHT))

                with self._lock:
                    self._frame = main_bgr
                    self._detect_frame = detect_bgr

            except Exception as exc:  # noqa: BLE001
                # Transient picamera2 / bus error — log once and retry next frame
                # rather than letting the thread die silently.
                _log.warning("Camera capture error (will retry): %s", exc)
                import time as _time
                _time.sleep(0.1)

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

    def grab_both_frames(self):
        """Return (main_bgr, detect_bgr) atomically under one lock acquisition.

        Calling grab_frame() and grab_detect_frame() separately acquires the
        lock twice; this method does it once so both frames always come from
        the same camera capture request.
        """
        with self._lock:
            main   = self._frame.copy()        if self._frame        is not None else None
            detect = self._detect_frame.copy() if self._detect_frame is not None else None
            return main, detect

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

