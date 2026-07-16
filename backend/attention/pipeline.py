"""
Unified attention pipeline — Objective 4 spike.

Combines FaceDetector (YuNet), HeadPoseEstimator (solvePnP), and an
EyeClosureDetector into a single synchronous callable.  Designed to
be a drop-in replacement for `detector.process(frame)` in camera_loop:

    # Objective 1 integration (after gate passes):
    detection = await loop.run_in_executor(None, pipeline.process, detect_frame)

All three stages run sequentially inside the executor thread so only one
thread slot is consumed per frame — the same pattern as the current
bare detector.process() call.

Attention logic
---------------
attention_ok is True if and only if ALL of the following hold:
  1. Exactly one face detected (YuNet)
  2. NOT looking_away (head pose) — skipped when pose_ok=False (benefit of doubt)
  3. NOT both_closed (eye closure)

attention_reason encodes the first failing condition as a string.

Output dict (extends the FaceDetector dict with new fields):
  {
    "face_detected":    bool,
    "face_count":       int,
    "attention_ok":     bool,
    "attention_reason": str,    # see ATTENTION_REASON_* constants
    "landmarks_2d":     ndarray | None,
    "bbox":             tuple | None,
    # Head pose (None when pose_ok=False):
    "yaw_deg":          float | None,
    "pitch_deg":        float | None,
    "roll_deg":         float | None,
    "pose_ok":          bool,
    # Eye closure:
    "left_eye_open":    bool | None,
    "right_eye_open":   bool | None,
    "both_closed":      bool,
    # Untested-eye monitor (Objective 2):
    "untested_eye_open_events":  int,
    "occlusion_confidence_low":  bool,
    "persistent_open":           bool,
  }
"""

from typing import Optional

import numpy as np

from face_detection import FaceDetector
from attention.head_pose import HeadPoseEstimator
from attention.eye_closure import EyeClosureDetector, MockEyeClosureDetector
from attention.untested_eye import UntestedEyeMonitor


# ---------------------------------------------------------------------------
# attention_reason constants (canonical strings)
# ---------------------------------------------------------------------------
REASON_OK               = "ok"
REASON_NO_FACE          = "no_face"
REASON_MULTIPLE_FACES   = "multiple_faces"
REASON_LOOKING_AWAY     = "looking_away"
REASON_EYES_CLOSED      = "both_eyes_closed"
REASON_UNTESTED_EYE     = "untested_eye_open"

# Consecutive frames with looking_away=True before triggering.
# At ~12 Hz (decimated attention loop): 3 frames ≈ 250 ms — eliminates
# single-frame jitter from noisy 5-point YuNet landmarks at 320×240.
LOOKING_AWAY_CONFIRM_FRAMES: int = 3


class AttentionPipeline:
    """
    Unified attention monitor combining face detection, head pose, and eye closure.

    Thread-safe when each frame is processed by at most one thread at a time
    (which is guaranteed by the run_in_executor call-site pattern in camera_loop).
    """

    def __init__(
        self,
        face_detector: FaceDetector,
        head_pose: Optional[HeadPoseEstimator] = None,
        eye_closure: Optional[EyeClosureDetector] = None,
    ) -> None:
        self._detector          = face_detector
        self._head_pose         = head_pose or HeadPoseEstimator()
        self._eye_closure       = eye_closure or MockEyeClosureDetector()
        self._untested_eye_mon  = UntestedEyeMonitor()
        self._looking_away_frames: int = 0   # consecutive looking_away frames

    def set_eye_tested(self, eye: str) -> None:
        """Called from handle_client on set_test_mode WS message."""
        self._untested_eye_mon.set_eye_tested(eye)

    def reset_eye_tested(self) -> None:
        """Reset to binocular mode on WS reconnect."""
        self._untested_eye_mon.reset()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process(self, bgr_frame: np.ndarray) -> dict:
        """
        Run the full attention pipeline on a 320×240 BGR frame.

        Returns a dict compatible with the existing camera_loop payload
        structure, extended with head-pose and eye-closure fields.
        """
        # Stage 1 — face detection (YuNet)
        face = self._detector.process(bgr_frame)

        # Fast-path: no face or multiple faces — skip secondary signals
        if not face["face_detected"] or face["face_count"] != 1:
            self._looking_away_frames = 0   # reset when face is lost
            # Still update untested-eye monitor so event counts stay accurate
            untested = self._untested_eye_mon.update(
                {"left_score": None, "right_score": None}
            )
            return self._build_result(face, None, None, untested)

        landmarks = face.get("landmarks_2d")
        bbox      = face.get("bbox")

        # Stage 2 — head pose (solvePnP, ~0.2–0.5 ms)
        pose = self._head_pose.estimate(landmarks)

        # Temporal smoothing: require LOOKING_AWAY_CONFIRM_FRAMES consecutive
        # looking_away=True before triggering. Eliminates single-frame noise
        # from noisy 5-point YuNet landmarks at 320×240.
        if pose["pose_ok"] and pose["looking_away"]:
            self._looking_away_frames += 1
        else:
            self._looking_away_frames = 0
        pose = {**pose, "looking_away": self._looking_away_frames >= LOOKING_AWAY_CONFIRM_FRAMES}

        # Stage 3 — eye closure (~4–8 ms with TFLite model; negligible with mock)
        closure = self._eye_closure.detect(bgr_frame, landmarks, bbox)

        # Stage 4 — untested-eye monitor (Objective 2; no-op in binocular mode)
        untested = self._untested_eye_mon.update(closure)

        return self._build_result(face, pose, closure, untested)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_result(
        face: dict,
        pose: Optional[dict],
        closure: Optional[dict],
        untested: Optional[dict] = None,
    ) -> dict:
        """Merge the four sub-results into a single attention dict."""

        # --- Defaults when secondary signals are unavailable ---
        if pose is None:
            pose = {"yaw_deg": None, "pitch_deg": None, "roll_deg": None,
                    "looking_away": False, "pose_ok": False}
        if closure is None:
            closure = {"left_eye_open": None, "right_eye_open": None,
                       "both_closed": False, "eye_closure_ok": True,
                       "left_score": None, "right_score": None}
        if untested is None:
            untested = {"attention_override": False, "persistent_open": False,
                        "untested_eye_open_events": 0, "occlusion_confidence_low": False}

        # --- Unified attention logic ---
        if not face["face_detected"] or face["face_count"] != 1:
            # Reason already set by face detector
            attention_ok     = False
            attention_reason = face["attention_reason"]  # no_face | multiple_faces

        elif pose["pose_ok"] and pose["looking_away"]:
            attention_ok     = False
            attention_reason = REASON_LOOKING_AWAY

        elif closure["both_closed"]:
            attention_ok     = False
            attention_reason = REASON_EYES_CLOSED

        elif untested["attention_override"]:
            attention_ok     = False
            attention_reason = REASON_UNTESTED_EYE

        else:
            attention_ok     = True
            attention_reason = REASON_OK

        return {
            # Core fields (backward-compatible with Objective 3)
            "face_detected":    face["face_detected"],
            "face_count":       face["face_count"],
            "attention_ok":     attention_ok,
            "attention_reason": attention_reason,
            "landmarks_2d":     face.get("landmarks_2d"),
            "bbox":             face.get("bbox"),
            # Head pose
            "yaw_deg":          pose["yaw_deg"],
            "pitch_deg":        pose["pitch_deg"],
            "roll_deg":         pose["roll_deg"],
            "pose_ok":          pose["pose_ok"],
            # Eye closure
            "left_eye_open":    closure["left_eye_open"],
            "right_eye_open":   closure["right_eye_open"],
            "both_closed":      closure["both_closed"],
            # Untested-eye monitor fields (Objective 2)
            "untested_eye_open_events": untested["untested_eye_open_events"],
            "occlusion_confidence_low": untested["occlusion_confidence_low"],
            "persistent_open":          untested["persistent_open"],
        }
