"""
Port of src/lib/distance.ts — distance estimation from MediaPipe face landmarks.

Uses the pinhole camera model:  d = f_px × D_real / P_measured

Three references with confidence weighting:
  1. Iris diameter  (landmarks 468-472 left, 473-477 right) — best < 2.5 m
  2. IPD            (landmark 468 & 473 centres)            — best 1-4 m
  3. Face width     (landmarks 234 & 454)                   — best 3-6 m
"""

import math
from typing import Optional
from constants import IRIS_DIAMETER_MM, DEFAULT_IPD_MM, AVG_FACE_WIDTH_MM


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dist2d(ax: float, ay: float, bx: float, by: float) -> float:
    return math.sqrt((ax - bx) ** 2 + (ay - by) ** 2)


def _default_focal_length(image_width: int) -> float:
    """Typical 60° horizontal FOV webcam / Pi Camera estimate."""
    h_fov_rad = math.radians(60)
    return (image_width / 2) / math.tan(h_fov_rad / 2)


# ---------------------------------------------------------------------------
# Focal-length calibration
# ---------------------------------------------------------------------------

def calibrate_focal_length(
    pixel_size: float,
    known_distance_m: float,
    real_size_mm: float,
) -> float:
    """f_px = P_measured × d / D_real"""
    return (pixel_size * known_distance_m) / (real_size_mm / 1000)


def auto_estimate_focal_length(image_width: int) -> float:
    """
    Pi Camera Module 3 typical horizontal FOV ≈ 66°.
    Pi Camera Module 2 ≈ 62°.  Use 64° as a safe default.
    Can be overridden once iris calibration data is available.
    """
    h_fov_rad = math.radians(64)
    return (image_width / 2) / math.tan(h_fov_rad / 2)


# ---------------------------------------------------------------------------
# Per-method estimators
# ---------------------------------------------------------------------------

def estimate_from_iris(
    landmarks: list,
    focal_length_px: float,
    image_width: int,
    image_height: int,
) -> Optional[dict]:
    """
    Estimate distance from iris diameter.
    Mirrors estimateFromIris() in distance.ts.
    """
    if len(landmarks) < 478:
        return None

    li469 = landmarks[469]
    li471 = landmarks[471]
    ri474 = landmarks[474]
    ri476 = landmarks[476]

    left_diam_px = _dist2d(
        li469.x * image_width, li469.y * image_height,
        li471.x * image_width, li471.y * image_height,
    )
    right_diam_px = _dist2d(
        ri474.x * image_width, ri474.y * image_height,
        ri476.x * image_width, ri476.y * image_height,
    )

    avg_iris_px = (left_diam_px + right_diam_px) / 2
    if avg_iris_px < 3:
        return None

    distance_m = (focal_length_px * (IRIS_DIAMETER_MM / 1000)) / avg_iris_px
    confidence = min(1.0, avg_iris_px / 20)

    return {"distance": distance_m, "confidence": confidence, "method": "iris",
            "iris_px": avg_iris_px}


def estimate_from_ipd(
    landmarks: list,
    focal_length_px: float,
    ipd_mm: float,
    image_width: int,
    image_height: int,
) -> Optional[dict]:
    """
    Estimate distance from inter-pupillary distance.
    Mirrors estimateFromIPD() in distance.ts.
    """
    if len(landmarks) < 478:
        return None

    left_center = landmarks[468]
    right_center = landmarks[473]

    ipd_px = _dist2d(
        left_center.x * image_width, left_center.y * image_height,
        right_center.x * image_width, right_center.y * image_height,
    )

    if ipd_px < 10:
        return None

    distance_m = (focal_length_px * (ipd_mm / 1000)) / ipd_px
    confidence = min(1.0, ipd_px / 50)

    return {"distance": distance_m, "confidence": confidence, "method": "ipd"}


def estimate_from_face_width(
    landmarks: list,
    focal_length_px: float,
    image_width: int,
    image_height: int,
) -> Optional[dict]:
    """
    Estimate distance from bizygomatic face width.
    Mirrors estimateFromFaceWidth() in distance.ts.
    """
    if len(landmarks) < 455:
        return None

    left = landmarks[234]
    right = landmarks[454]

    face_width_px = _dist2d(
        left.x * image_width, left.y * image_height,
        right.x * image_width, right.y * image_height,
    )

    if face_width_px < 20:
        return None

    distance_m = (focal_length_px * (AVG_FACE_WIDTH_MM / 1000)) / face_width_px
    confidence = min(1.0, face_width_px / 100) * 0.7  # lower max confidence

    return {"distance": distance_m, "confidence": confidence, "method": "face_width"}


# ---------------------------------------------------------------------------
# Fusion
# ---------------------------------------------------------------------------

def fuse_distance_estimates(estimates: list) -> dict:
    """
    Confidence-weighted average of multiple estimates.
    Mirrors fuseDistanceEstimates() in distance.ts.
    """
    valid = [e for e in estimates if e and 0.1 < e["distance"] < 10]
    if not valid:
        return {"distance": 0.0, "confidence": 0.0}

    total_weight = sum(e["confidence"] for e in valid)
    weighted_sum = sum(e["distance"] * e["confidence"] for e in valid)

    return {
        "distance": weighted_sum / total_weight,
        "confidence": min(1.0, total_weight / len(valid)),
    }
