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


import urllib.request
from pathlib import Path

import cv2
import numpy as np

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
# Minimal landmark stub — mirrors MediaPipe landmark attributes
# ---------------------------------------------------------------------------

class _LM:
    """Normalised (0-1) landmark with .x .y .z — mirrors MediaPipe landmark."""
    __slots__ = ("x", "y", "z")

    def __init__(self, x: float, y: float) -> None:
        self.x = float(x)
        self.y = float(y)
        self.z = 0.0


# ---------------------------------------------------------------------------
# FaceDetector
# ---------------------------------------------------------------------------

class FaceDetector:
    """
    Wraps cv2.FaceDetectorYN (YuNet) — drop-in replacement for the old
    MediaPipe FaceMesh-based detector.

    Constructor accepts the same kwargs as the old class so main.py
    needs no changes.
    """

    def __init__(
        self,
        max_num_faces: int = 1,
        score_threshold: float = 0.6,
        nms_threshold: float = 0.3,
        # MediaPipe-compat kwargs (ignored by YuNet)
        refine_landmarks: bool = True,
        min_detection_confidence: float = 0.5,
        min_tracking_confidence: float = 0.5,
    ) -> None:
        model_path = _ensure_model()
        self._detector = cv2.FaceDetectorYN.create(
            model_path,
            "",
            (320, 320),   # initial input size — overridden per frame in process()
            score_threshold,
            nms_threshold,
            max_num_faces,
        )
        self._max_faces = max_num_faces

    def process(self, bgr_frame: np.ndarray) -> dict:
        """
        Detect faces in a BGR frame.

        Returns the same dict shape as the old MediaPipe detector:
          {
            "face_detected": bool,
            "face_count":    int,
            "landmarks":     list | None,
          }
        """
        h, w = bgr_frame.shape[:2]
        self._detector.setInputSize((w, h))
        _, faces = self._detector.detect(bgr_frame)

        if faces is None or len(faces) == 0:
            return {"face_detected": False, "face_count": 0, "landmarks": None}

        # Sort by confidence (highest first) and cap at max_num_faces
        faces = sorted(faces, key=lambda f: f[14], reverse=True)[: self._max_faces]
        face_count = len(faces)

        landmarks = _build_landmarks(faces[0], w, h)

        return {
            "face_detected": True,
            "face_count": face_count,
            "landmarks": landmarks,
        }

    def close(self) -> None:
        pass  # cv2 objects are reference-counted


# ---------------------------------------------------------------------------
# Internal: build landmark list compatible with distance.py
# ---------------------------------------------------------------------------

def _build_landmarks(face: np.ndarray, img_w: int, img_h: int):
    """
    Build a 500-item sparse list from a single YuNet face row.

    YuNet face row layout:
      face[0:4]   bbox  (x, y, w, h)
      face[4:6]   right eye centre  (x, y)
      face[6:8]   left  eye centre  (x, y)
      face[8:10]  nose tip
      face[10:12] right mouth corner
      face[12:14] left  mouth corner
      face[14]    confidence score

    Populated indices:
      468-472   left  iris ring → all mapped to left  eye centre
      473-477   right iris ring → all mapped to right eye centre
      234       left  cheek    → left  bbox edge (8% inset)
      454       right cheek    → right bbox edge (8% inset)
    """
    x, y, bw, bh = face[0], face[1], face[2], face[3]
    right_eye_x, right_eye_y = face[4], face[5]
    left_eye_x,  left_eye_y  = face[6], face[7]

    lms = [None] * 500

    # Eye-centre / iris landmarks
    # All 5 points in each iris ring are identical → diameter = 0
    # → estimate_from_iris() returns None (< 3 px guard) — intended
    # estimate_from_ipd() uses lms[468] and lms[473] — these are eye centres ✓
    left_eye  = _LM(left_eye_x  / img_w, left_eye_y  / img_h)
    right_eye = _LM(right_eye_x / img_w, right_eye_y / img_h)
    for idx in range(468, 473):   # 468 469 470 471 472
        lms[idx] = left_eye
    for idx in range(473, 478):   # 473 474 475 476 477
        lms[idx] = right_eye

    # Cheek / face-width landmarks
    # 8% inset on each side → ~84% of bbox width ≈ bizygomatic face width
    inset  = bw * 0.08
    cheek_y = (y + bh * 0.58) / img_h   # ≈ cheekbone height in face
    lms[234] = _LM((x + inset)      / img_w, cheek_y)
    lms[454] = _LM((x + bw - inset) / img_w, cheek_y)

    return lms
