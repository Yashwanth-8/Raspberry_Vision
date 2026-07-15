"""
Attention monitoring — YuNet face detection + head pose + eye analysis.

Four features, all via pure OpenCV (no additional models or downloads):

  1. Face presence / absence   → no_face
  2. Multiple face detection   → multiple_faces
  3. Head pose (solvePnP)      → head_turned   [yaw left/right, pitch up/down]
  4. Eye closure tracking      → eyes_closed   [both eyes closed > threshold]
  5. Iris / gaze estimation    → gaze_away     [iris blob offset in eye crop]

Detection runs on the 320×240 canvas for fast YuNet inference.
Eye analysis (features 3–5) runs on the full 720p main frame so eye crops
are ~90 px wide — large enough for reliable blob detection.

process(detect_frame, main_frame) returns:
  {
    "face_detected":    bool,
    "face_count":       int,
    "attention_ok":     bool,
    "attention_reason": str,     # "ok"|"no_face"|"multiple_faces"|
                                 # "head_turned"|"eyes_closed"|"gaze_away"
    "head_yaw_deg":     float,   # negative=left, positive=right
    "head_pitch_deg":   float,   # negative=down, positive=up
    "eyes_closed":      bool,
    "gaze_offset":      float,   # normalised −1…+1 (0=centre)
  }
"""

import math
import time
import urllib.request
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np

from constants import (
    DETECT_WIDTH, DETECT_HEIGHT, CAMERA_WIDTH, CAMERA_HEIGHT,
    HEAD_YAW_THRESHOLD_DEG, HEAD_PITCH_THRESHOLD_DEG,
    EYES_CLOSED_THRESHOLD_S, GAZE_OFFSET_THRESHOLD,
)

# ---------------------------------------------------------------------------
# YuNet model
# ---------------------------------------------------------------------------
_MODEL_URL  = (
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
# Head-pose constants
# ---------------------------------------------------------------------------
# Camera matrix for 1280×720 assuming ~64° horizontal FOV
_F   = (CAMERA_WIDTH / 2) / math.tan(math.radians(32))
_CAM = np.array(
    [[_F, 0, CAMERA_WIDTH / 2], [0, _F, CAMERA_HEIGHT / 2], [0, 0, 1]],
    dtype=np.float64,
)
_DIST = np.zeros((4, 1), dtype=np.float64)

# 3-D face reference points (mm), matched to YuNet's 5 landmark order:
#   nose_tip, right_eye_centre, left_eye_centre, right_mouth, left_mouth
# (X+ = camera-right, Y+ = camera-down, Z+ = depth away from camera)
_FACE_3D = np.array([
    [  0.0,   0.0,   0.0],   # Nose tip (origin)
    [ 58.0, -38.0, -12.0],   # Right eye centre
    [-58.0, -38.0, -12.0],   # Left eye centre
    [ 40.0,  32.0, -12.0],   # Right mouth corner
    [-40.0,  32.0, -12.0],   # Left mouth corner
], dtype=np.float64)

# Scale factors: 320×240 detect canvas → 1280×720 main frame
_SX = CAMERA_WIDTH  / DETECT_WIDTH    # 4.0
_SY = CAMERA_HEIGHT / DETECT_HEIGHT   # 3.0


# ---------------------------------------------------------------------------
# FaceDetector
# ---------------------------------------------------------------------------
class FaceDetector:
    """YuNet face detection + solvePnP head pose + iris blob eye analysis."""

    def __init__(
        self,
        max_num_faces: int = 2,
        score_threshold: float = 0.6,
        nms_threshold: float = 0.3,
        # Legacy kwargs — kept for backward compat with main.py
        refine_landmarks: bool = True,
        min_detection_confidence: float = 0.5,
        min_tracking_confidence: float = 0.5,
    ) -> None:
        model_path = _ensure_model()
        self._detector = cv2.FaceDetectorYN.create(
            model_path, "", (DETECT_WIDTH, DETECT_HEIGHT),
            score_threshold, nms_threshold, max_num_faces,
        )

        # Blob detector — finds dark circular regions (iris) in eye crops
        p = cv2.SimpleBlobDetector_Params()
        p.filterByColor      = True;  p.blobColor      = 0      # dark blobs
        p.filterByArea       = True;  p.minArea        = 20.0;  p.maxArea = 2000.0
        p.filterByCircularity = False
        p.filterByConvexity   = False
        p.filterByInertia     = False
        self._blob = cv2.SimpleBlobDetector_create(p)

        # Eye-closure state: monotonic timestamp when both eyes first closed
        self._eyes_closed_since: Optional[float] = None

    # ------------------------------------------------------------------
    def process(
        self,
        detect_frame: np.ndarray,
        main_frame: Optional[np.ndarray] = None,
    ) -> dict:
        """Run all attention checks. main_frame enables eye + head analysis."""

        # ── 1. YuNet on 320×240 ──────────────────────────────────────────
        if detect_frame.shape[:2] != (DETECT_HEIGHT, DETECT_WIDTH):
            detect_frame = cv2.resize(detect_frame, (DETECT_WIDTH, DETECT_HEIGHT))

        self._detector.setInputSize((DETECT_WIDTH, DETECT_HEIGHT))
        _, faces = self._detector.detect(detect_frame)

        if faces is None or len(faces) == 0:
            self._eyes_closed_since = None
            return self._result(False, 0, False, "no_face")

        faces = sorted(faces, key=lambda f: f[14], reverse=True)

        if len(faces) > 1:
            self._eyes_closed_since = None
            return self._result(True, len(faces), False, "multiple_faces")

        primary = faces[0]

        # Defaults when main_frame is unavailable (camera warming up)
        yaw = pitch = gaze = 0.0
        eyes_closed = False

        if main_frame is not None:
            # ── 2. Head pose via solvePnP ─────────────────────────────────
            yaw, pitch = self._head_pose(primary)

            # ── 3+4+5. Eye crops → closure + gaze ───────────────────────
            l_crop, r_crop = self._crop_eyes(main_frame, primary)
            l_open, l_off  = self._analyze_eye(l_crop)
            r_open, r_off  = self._analyze_eye(r_crop)

            # Both eyes closed when neither has a detectable iris blob
            both_closed = not l_open and not r_open
            if both_closed:
                if self._eyes_closed_since is None:
                    self._eyes_closed_since = time.monotonic()
                closed_s = time.monotonic() - self._eyes_closed_since
            else:
                self._eyes_closed_since = None
                closed_s = 0.0

            eyes_closed = closed_s >= EYES_CLOSED_THRESHOLD_S

            # Mean iris offset (use only open eyes; 0 if both closed)
            open_offsets = [o for open_, o in [(l_open, l_off), (r_open, r_off)] if open_]
            gaze = float(sum(open_offsets) / len(open_offsets)) if open_offsets else 0.0
        else:
            self._eyes_closed_since = None

        # ── Attention decision (priority order) ────────────────────────────
        if abs(yaw) > HEAD_YAW_THRESHOLD_DEG or abs(pitch) > HEAD_PITCH_THRESHOLD_DEG:
            reason, ok = "head_turned", False
        elif eyes_closed:
            reason, ok = "eyes_closed", False
        elif abs(gaze) > GAZE_OFFSET_THRESHOLD:
            reason, ok = "gaze_away", False
        else:
            reason, ok = "ok", True

        return {
            "face_detected":    True,
            "face_count":       1,
            "attention_ok":     ok,
            "attention_reason": reason,
            "head_yaw_deg":     round(yaw,   1),
            "head_pitch_deg":   round(pitch, 1),
            "eyes_closed":      eyes_closed,
            "gaze_offset":      round(gaze,  3),
        }

    # ------------------------------------------------------------------
    @staticmethod
    def _result(detected: bool, count: int, ok: bool, reason: str) -> dict:
        return {
            "face_detected":    detected,
            "face_count":       count,
            "attention_ok":     ok,
            "attention_reason": reason,
            "head_yaw_deg":     0.0,
            "head_pitch_deg":   0.0,
            "eyes_closed":      False,
            "gaze_offset":      0.0,
        }

    # ------------------------------------------------------------------
    def _head_pose(self, face: np.ndarray) -> Tuple[float, float]:
        """Return (yaw_deg, pitch_deg) via solvePnP on YuNet's 5 landmarks."""
        pts = np.array([
            [face[8]  * _SX, face[9]  * _SY],   # nose tip
            [face[4]  * _SX, face[5]  * _SY],   # right eye
            [face[6]  * _SX, face[7]  * _SY],   # left eye
            [face[10] * _SX, face[11] * _SY],   # right mouth
            [face[12] * _SX, face[13] * _SY],   # left mouth
        ], dtype=np.float64)

        ok, rvec, _ = cv2.solvePnP(
            _FACE_3D, pts, _CAM, _DIST, flags=cv2.SOLVEPNP_ITERATIVE
        )
        if not ok:
            return 0.0, 0.0

        R, _ = cv2.Rodrigues(rvec)
        sy = math.sqrt(R[0, 0] ** 2 + R[1, 0] ** 2)
        if sy > 1e-6:
            pitch = math.degrees(math.atan2(-R[2, 1],  R[2, 2]))
            yaw   = math.degrees(math.atan2( R[2, 0],  sy))
        else:
            pitch = math.degrees(math.atan2(-R[1, 2],  R[1, 1]))
            yaw   = math.degrees(math.atan2( R[2, 0],  sy))
        return float(yaw), float(pitch)

    # ------------------------------------------------------------------
    def _crop_eyes(
        self, frame: np.ndarray, face: np.ndarray
    ) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        """Crop left and right eye regions from the 720p frame."""
        bw  = face[2] * _SX                 # face bbox width in 720p pixels
        ew  = max(24, int(bw * 0.35))       # eye crop width  (~35 % of face)
        eh  = max(12, int(ew * 0.48))       # eye crop height (~48 % of width)

        def crop(cx: float, cy: float) -> Optional[np.ndarray]:
            cx_i, cy_i = int(cx * _SX), int(cy * _SY)
            x1 = max(0, cx_i - ew // 2);  x2 = min(frame.shape[1], x1 + ew)
            y1 = max(0, cy_i - eh // 2);  y2 = min(frame.shape[0], y1 + eh)
            return frame[y1:y2, x1:x2] if (x2 - x1 >= 12 and y2 - y1 >= 6) else None

        # face[6:8] = left eye,  face[4:6] = right eye  (YuNet convention)
        return crop(face[6], face[7]), crop(face[4], face[5])

    # ------------------------------------------------------------------
    def _analyze_eye(
        self, eye_crop: Optional[np.ndarray]
    ) -> Tuple[bool, float]:
        """
        Detect iris in eye crop.

        Returns:
          eye_open (bool)      — False means no iris blob → eye likely closed.
          iris_x_norm (float)  — normalised −1…+1; 0 = eye centre.
        """
        if eye_crop is None or eye_crop.size < 60:
            return True, 0.0   # too small to analyse → assume open

        gray = cv2.cvtColor(eye_crop, cv2.COLOR_BGR2GRAY)
        keypoints = self._blob.detect(gray)

        if not keypoints:
            return False, 0.0  # no dark blob → iris not visible → eye closed

        best  = max(keypoints, key=lambda k: k.size)
        w     = eye_crop.shape[1]
        norm  = float((best.pt[0] - w / 2) / (w / 2))   # −1…+1
        return True, norm

    # ------------------------------------------------------------------
    def close(self) -> None:
        pass  # cv2 objects are reference-counted


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
