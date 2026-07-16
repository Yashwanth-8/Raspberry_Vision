"""
Head-pose estimation via cv2.solvePnP on YuNet's 5 facial landmarks.

Objective 4 — architecture spike deliverable.
Will be integrated into the unified attention pipeline in Objective 1,
after the executor decision gate is confirmed on Pi 4 hardware.

Algorithm
---------
YuNet provides 5 2-D image landmarks:
  kpt0  right eye centre  (person's right → image left for frontal face)
  kpt1  left eye centre
  kpt2  nose tip
  kpt3  right mouth corner
  kpt4  left mouth corner

We map these to a canonical 3-D face model (5 points, units mm, nose tip
at origin) and call cv2.solvePnP (SOLVEPNP_SQPNP) to recover the rotation
vector. cv2.Rodrigues converts it to a 3×3 rotation matrix; standard
matrix decomposition gives yaw, pitch, roll in degrees.

A reprojection error check is included: if the solved pose projects the 3-D
model points back with an RMS error > REPROJECTION_ERROR_THRESHOLD px, the
pose is treated as unreliable (pose_ok=False, looking_away=False).

Performance on Pi 4 (estimated)
---------------------------------
solvePnP with 5 points:  ~0.2–0.5 ms wall time.
GIL is released during OpenCV C++ computation → efficient with ThreadPoolExecutor.

Usage
-----
    estimator = HeadPoseEstimator()
    result = estimator.estimate(landmarks_2d, image_width=320, image_height=240)
    if result["pose_ok"] and result["looking_away"]:
        ...
"""

import math
from typing import Optional, Tuple

import cv2
import numpy as np

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

# Angles (degrees) beyond which the patient is considered to be looking away.
# Adjust after rig calibration if the thresholds produce too many false resets.
YAW_THRESHOLD_DEG: float = 20.0    # left/right head rotation
                                    # Lowered from 30°: 30° was too permissive at 320×240
PITCH_THRESHOLD_DEG: float = 25.0  # up/down head tilt

# If the solved pose re-projects the model with RMS > this value (pixels),
# the pose is rejected as unreliable.
# YuNet landmarks at 320×240 carry ±3–5 px noise; minimum achievable RMS for a
# good 5-point fit is therefore ~4–8 px.  The original 5 px threshold was
# rejecting nearly all valid poses → pose_ok=False → gaze check fully bypassed.
# 12 px accepts good fits while rejecting truly garbage estimates.
REPROJECTION_ERROR_THRESHOLD_PX: float = 12.0

# ---------------------------------------------------------------------------
# 3-D reference face model
# ---------------------------------------------------------------------------
# Canonical 5-point face in millimetres, nose tip at origin.
# Axes: +x right, +y up, +z toward the camera (OpenCV right-hand convention).
# These are approximate average adult measurements; they do not need to be
# exact — only the ratios between landmarks affect the angle estimate.
_MODEL_3D = np.array([
    [-45.0,  50.0, -30.0],  # kpt0  right eye centre
    [ 45.0,  50.0, -30.0],  # kpt1  left eye centre
    [  0.0,   0.0,   0.0],  # kpt2  nose tip  (origin)
    [-32.0, -50.0, -35.0],  # kpt3  right mouth corner
    [ 32.0, -50.0, -35.0],  # kpt4  left mouth corner
], dtype=np.float64)


# ---------------------------------------------------------------------------
# HeadPoseEstimator
# ---------------------------------------------------------------------------

class HeadPoseEstimator:
    """
    Estimates head yaw/pitch/roll from YuNet's 5 facial landmarks.

    A single instance is created once at startup and reused across frames.
    process() is thread-safe (no mutable state is modified during inference).
    """

    def __init__(
        self,
        focal_length_px: Optional[float] = None,
        yaw_threshold_deg: float = YAW_THRESHOLD_DEG,
        pitch_threshold_deg: float = PITCH_THRESHOLD_DEG,
        reprojection_threshold_px: float = REPROJECTION_ERROR_THRESHOLD_PX,
    ) -> None:
        """
        Parameters
        ----------
        focal_length_px
            Camera focal length in pixels at 320×240.  If None, estimated
            from a 62° horizontal FOV assumption (Pi Camera Module v2 default).
            Override with a calibrated value from camera.py or optotype.ts.
        """
        self._focal_px = focal_length_px  # resolved in estimate() using image dims
        self._yaw_thr = yaw_threshold_deg
        self._pitch_thr = pitch_threshold_deg
        self._reproj_thr = reprojection_threshold_px

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def estimate(
        self,
        landmarks_2d: Optional[np.ndarray],
        image_width: int = 320,
        image_height: int = 240,
    ) -> dict:
        """
        Estimate head pose from 5 YuNet landmark points.

        Parameters
        ----------
        landmarks_2d
            np.ndarray of shape (5, 2) float32 — pixel coords in the
            detection canvas (320×240).  If None, returns pose_ok=False.
        image_width, image_height
            Detection canvas dimensions (almost always 320×240).

        Returns
        -------
        dict with keys:
            yaw_deg      : float | None
            pitch_deg    : float | None
            roll_deg     : float | None
            looking_away : bool   — True when |yaw|>threshold or |pitch|>threshold
            pose_ok      : bool   — False when solvePnP failed or reprojection too large
        """
        _NO_POSE = {
            "yaw_deg": None, "pitch_deg": None, "roll_deg": None,
            "looking_away": False, "pose_ok": False,
        }

        if landmarks_2d is None or landmarks_2d.shape != (5, 2):
            return _NO_POSE

        # Build camera matrix for this canvas size
        cam_matrix = self._camera_matrix(image_width, image_height)
        dist_coeffs = np.zeros((4, 1), dtype=np.float64)

        image_points = landmarks_2d.astype(np.float64)

        try:
            success, rvec, tvec = cv2.solvePnP(
                _MODEL_3D,
                image_points,
                cam_matrix,
                dist_coeffs,
                flags=cv2.SOLVEPNP_SQPNP,
            )
        except cv2.error:
            return _NO_POSE

        if not success:
            return _NO_POSE

        # Reprojection error check
        reproj_error = self._reprojection_error(
            _MODEL_3D, rvec, tvec, cam_matrix, dist_coeffs, image_points
        )
        if reproj_error > self._reproj_thr:
            return _NO_POSE

        # Rotation vector → Euler angles
        yaw, pitch, roll = self._rvec_to_euler(rvec)

        looking_away = (
            abs(yaw) > self._yaw_thr or
            abs(pitch) > self._pitch_thr
        )

        return {
            "yaw_deg": round(yaw, 1),
            "pitch_deg": round(pitch, 1),
            "roll_deg": round(roll, 1),
            "looking_away": looking_away,
            "pose_ok": True,
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _camera_matrix(self, width: int, height: int) -> np.ndarray:
        """Build a pinhole camera matrix for the given canvas size."""
        if self._focal_px is not None:
            f = self._focal_px
        else:
            # Pi Camera Module v2: ~62° HFOV.  f = (w/2) / tan(HFOV/2).
            h_fov_rad = math.radians(62.0)
            f = (width / 2.0) / math.tan(h_fov_rad / 2.0)
        cx, cy = width / 2.0, height / 2.0
        return np.array([
            [f,   0.0, cx],
            [0.0, f,   cy],
            [0.0, 0.0, 1.0],
        ], dtype=np.float64)

    @staticmethod
    def _reprojection_error(
        object_points: np.ndarray,
        rvec: np.ndarray,
        tvec: np.ndarray,
        cam_matrix: np.ndarray,
        dist_coeffs: np.ndarray,
        image_points: np.ndarray,
    ) -> float:
        projected, _ = cv2.projectPoints(
            object_points, rvec, tvec, cam_matrix, dist_coeffs
        )
        projected = projected.reshape(-1, 2)
        errors = np.linalg.norm(projected - image_points, axis=1)
        return float(np.sqrt(np.mean(errors ** 2)))

    @staticmethod
    def _rvec_to_euler(rvec: np.ndarray) -> Tuple[float, float, float]:
        """
        Convert a rotation vector (Rodrigues) to yaw, pitch, roll in degrees.

        Convention (OpenCV camera space):
          yaw   — rotation around Y axis  (left/right, positive = face turned right)
          pitch — rotation around X axis  (up/down,   positive = face tilted up)
          roll  — rotation around Z axis  (in-plane)
        """
        R, _ = cv2.Rodrigues(rvec)
        # Decompose R into yaw-pitch-roll (Tait-Bryan ZYX extrinsic)
        pitch = math.degrees(math.atan2(-R[2, 0], math.sqrt(R[0, 0]**2 + R[1, 0]**2)))
        yaw   = math.degrees(math.atan2(R[1, 0] / math.cos(math.radians(pitch)),
                                         R[0, 0] / math.cos(math.radians(pitch))))
        roll  = math.degrees(math.atan2(R[2, 1] / math.cos(math.radians(pitch)),
                                         R[2, 2] / math.cos(math.radians(pitch))))
        return yaw, pitch, roll
