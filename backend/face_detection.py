"""
Attention monitoring using YuNet face detector.

With the HC-SR04 ultrasonic sensor now handling all distance measurement,
the camera's sole job is to verify the user is correctly engaged with the
test and pause when they are not.

Detection always runs on a fixed 320×240 canvas (the main camera frame resized)
to avoid the setInputSize coordinate-scaling bug present in older OpenCV
builds shipped with Raspberry Pi OS, and to keep inference fast (~8 ms on Pi 4).

process() returns:
  {                                      
    "face_detected":    bool,            
    "face_count":       int,             
    "attention_ok":     bool,   # True → single face present, test may run
    "attention_reason": str,    # "ok" | "no_face" | "multiple_faces"
  }
"""

import urllib.request
from pathlib import Path

import cv2
import numpy as np

from constants import DETECT_WIDTH, DETECT_HEIGHT

# ---------------------------------------------------------------------------
# YuNet model — downloaded automatically on first run (~80 KB)
# ---------------------------------------------------------------------------

_MODEL_URL = (
    "https://github.com/opencv/opencv_zoo/raw/main/"
    "models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
)
_MODEL_PATH = Path(__file__).parent / "models" / "face_detection_yunet_2023mar.onnx"


def _ensure_model() -> str:
    if not _MODEL_PATH.exists():
        _MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        print(f"[FaceDetector] Downloading YuNet model → {_MODEL_PATH} (~80 KB)…")
        try:
            urllib.request.urlretrieve(_MODEL_URL, _MODEL_PATH)
            print("[FaceDetector] Model downloaded OK.")
        except Exception as exc:
            raise RuntimeError(
                f"[FaceDetector] Could not download YuNet model: {exc}\n"
                f"  Download manually from:\n  {_MODEL_URL}\n"
                f"  and place at: {_MODEL_PATH}"
            ) from exc
    return str(_MODEL_PATH)


# ---------------------------------------------------------------------------
# FaceDetector — attention monitor
# ---------------------------------------------------------------------------

class FaceDetector:
    """
    Wraps cv2.FaceDetectorYN (YuNet) for attention monitoring.

    The detector is created once at the fixed detection canvas size
    (320×240). The process() method always resizes its input to that
    size before calling detect(), so setInputSize is always called with
    the same value — avoiding the coordinate-scaling bug in older OpenCV.
    """

    def __init__(
        self,
        max_num_faces: int = 2,          # detect up to 2 so we can flag intruders
        score_threshold: float = 0.6,
        nms_threshold: float = 0.3,
        # Legacy kwargs kept for backward compat with main.py call-site
        refine_landmarks: bool = True,
        min_detection_confidence: float = 0.5,
        min_tracking_confidence: float = 0.5,
    ) -> None:
        model_path = _ensure_model()
        # Fixed size matching the detection canvas — never changes
        self._detector = cv2.FaceDetectorYN.create(
            model_path,
            "",
            (DETECT_WIDTH, DETECT_HEIGHT),
            score_threshold,
            nms_threshold,
            max_num_faces,
        )

    def process(self, bgr_frame: np.ndarray) -> dict:
        """
        Detect faces and evaluate attention.

        Rules (prototype-safe):
          - no_face       → attention_ok=False  (person left / camera blocked)
          - multiple_faces → attention_ok=False  (intruder / cheating)
          - single face   → attention_ok=True   (normal test condition)

        Note: centring and gaze-direction checks were removed because at
        320×240 the landmark positions are only accurate to ±3–5 px, making
        those thresholds unreliable on a prototype rig. They can be re-added
        once the physical enclosure enforces a fixed head position.
        """
        # Always process at fixed canvas size → stable coordinate output
        if bgr_frame.shape[:2] != (DETECT_HEIGHT, DETECT_WIDTH):
            bgr_frame = cv2.resize(bgr_frame, (DETECT_WIDTH, DETECT_HEIGHT))

        self._detector.setInputSize((DETECT_WIDTH, DETECT_HEIGHT))
        _, faces = self._detector.detect(bgr_frame)

        # ---- No face ----
        if faces is None or len(faces) == 0:
            return {
                "face_detected": False,
                "face_count": 0,
                "attention_ok": False,
                "attention_reason": "no_face",
            }

        faces = sorted(faces, key=lambda f: f[14], reverse=True)
        face_count = len(faces)

        # ---- Multiple people / obstruction ----
        if face_count > 1:
            return {
                "face_detected": True,
                "face_count": face_count,
                "attention_ok": False,
                "attention_reason": "multiple_faces",
            }

        # ---- Single face present → test may proceed ----
        return {
            "face_detected": True,
            "face_count": 1,
            "attention_ok": True,
            "attention_reason": "ok",
        }

    def close(self) -> None:
        pass  # cv2 objects are reference-counted
