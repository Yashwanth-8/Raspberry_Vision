"""
Per-eye open/closed detection.

Objective 4 — architecture spike deliverable.
The model is NOT yet selected; this module defines the interface, implements
the eye-region crop logic, and provides a MockEyeClosureDetector for the
spike benchmark and tests.  The TFLite adapter (TFLiteEyeClosureDetector)
is stubbed with a full docstring; it will be completed in Objective 1 once
the spike acceptance criteria are confirmed on Pi 4 hardware.

Why no classical EAR?
----------------------
YuNet provides only 5 landmark points (eye centres, nose, mouth corners) —
no eyelid contours.  The Eye Aspect Ratio requires upper/lower eyelid points
(typically ≥ 4 per eye), which YuNet does not supply.  A lightweight model
is therefore the minimum-viable feature extractor for this signal, consistent
with the classical-first policy (classical analysis on model-derived features).

Crop strategy
-------------
Both eye regions are cropped from the 320×240 detection canvas using the
YuNet bounding box and eye-centre landmarks:
  - eye_half = max(8, int(0.18 * bbox_width))   ≈ 10-14 px at 320×240
  - left patch:  frame[ley-half:ley+half, lex-half:lex+half]
  - right patch: frame[rey-half:rey+half, rex-half:rex+half]
Patches are resized to MODEL_INPUT_SIZE × MODEL_INPUT_SIZE (32×32) and
normalised to [0, 1] float32 before inference.

Model selection (to be finalised in Objective 1)
-------------------------------------------------
Candidate: a MobileNetV3-Small int8 binary classifier (open/closed) with
  - Input  : 1 × 32 × 32 × 1  (grayscale, float32, normalised [0, 1])
  - Output : 1 × 1  (probability eye is OPEN; > OPEN_THRESHOLD → open)
  - Max latency target: ≤ 4 ms per inference at int8 on Pi 4
  - Two eyes: ≤ 8 ms total (both inferences sequential to avoid thread contention)

Candidate training set: MRL Eye Dataset (84k images, balanced open/closed)
  https://mrl.cs.vsb.cz/eyedataset

Interface
---------
All detectors share the `EyeClosureResult` return type:

  {
    "left_eye_open":  bool | None,  # None when crop failed or model unavailable
    "right_eye_open": bool | None,
    "left_score":     float | None, # probability open ∈ [0, 1]
    "right_score":    float | None,
    "both_closed":    bool,         # True only when BOTH eyes are confirmed closed
    "eye_closure_ok": bool,         # True unless both_closed confirmed
  }
"""

from abc import ABC, abstractmethod
from typing import Optional, Tuple

import cv2
import numpy as np

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MODEL_INPUT_SIZE: int = 32          # px — crop rescaled to this before inference
OPEN_THRESHOLD: float = 0.5         # score > threshold → eye is open
CROP_SCALE: float = 0.18            # eye-half as a fraction of bbox width
MIN_CROP_HALF_PX: int = 8           # minimum half-size to avoid degenerate crops


# ---------------------------------------------------------------------------
# Crop helper
# ---------------------------------------------------------------------------

def _crop_eye(
    frame: np.ndarray,
    cx: float,
    cy: float,
    half: int,
    out_size: int,
) -> Optional[np.ndarray]:
    """
    Crop a square eye patch centred at (cx, cy) with side 2*half from frame.

    Returns a normalised float32 array of shape (out_size, out_size, 1),
    or None if the crop is out-of-bounds or degenerate.
    """
    h, w = frame.shape[:2]
    x1, y1 = int(cx) - half, int(cy) - half
    x2, y2 = int(cx) + half, int(cy) + half

    if x1 < 0 or y1 < 0 or x2 > w or y2 > h or (x2 - x1) < 4 or (y2 - y1) < 4:
        return None

    patch = frame[y1:y2, x1:x2]
    if patch.size == 0:
        return None

    if patch.ndim == 3:
        patch = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)

    patch = cv2.resize(patch, (out_size, out_size))
    patch = patch.astype(np.float32) / 255.0
    return patch[..., np.newaxis]   # (H, W, 1)


def crop_eye_patches(
    frame: np.ndarray,
    landmarks_2d: np.ndarray,
    bbox: Tuple[int, int, int, int],
) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    """
    Crop right-eye and left-eye patches from the detection canvas.

    Parameters
    ----------
    frame       : 320×240 BGR frame
    landmarks_2d: (5, 2) float32 — YuNet landmarks
    bbox        : (x, y, w, h) face bounding box

    Returns
    -------
    (right_patch, left_patch) each of shape (32, 32, 1) float32, or None
    """
    _, _, bw, _ = bbox
    half = max(MIN_CROP_HALF_PX, int(CROP_SCALE * bw))

    right_eye_x, right_eye_y = landmarks_2d[0]  # kpt0
    left_eye_x,  left_eye_y  = landmarks_2d[1]  # kpt1

    right_patch = _crop_eye(frame, right_eye_x, right_eye_y, half, MODEL_INPUT_SIZE)
    left_patch  = _crop_eye(frame, left_eye_x,  left_eye_y,  half, MODEL_INPUT_SIZE)

    return right_patch, left_patch


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class EyeClosureDetector(ABC):
    """Abstract interface for eye-closure detectors."""

    @abstractmethod
    def detect(
        self,
        frame: np.ndarray,
        landmarks_2d: Optional[np.ndarray],
        bbox: Optional[Tuple[int, int, int, int]],
    ) -> dict:
        """
        Detect whether each eye is open or closed.

        Returns an EyeClosureResult dict (see module docstring).
        When landmarks_2d or bbox is None, returns safe defaults (both_closed=False).
        """

    @staticmethod
    def _make_result(
        left_score: Optional[float],
        right_score: Optional[float],
    ) -> dict:
        left_open  = None if left_score  is None else left_score  > OPEN_THRESHOLD
        right_open = None if right_score is None else right_score > OPEN_THRESHOLD

        # both_closed is True only when BOTH are positively confirmed closed
        both_closed = (left_open is False) and (right_open is False)

        return {
            "left_eye_open":  left_open,
            "right_eye_open": right_open,
            "left_score":     round(left_score,  3) if left_score  is not None else None,
            "right_score":    round(right_score, 3) if right_score is not None else None,
            "both_closed":    both_closed,
            "eye_closure_ok": not both_closed,
        }


# ---------------------------------------------------------------------------
# Mock detector  (spike / testing)
# ---------------------------------------------------------------------------

class MockEyeClosureDetector(EyeClosureDetector):
    """
    Stand-in detector for benchmarking and unit tests.

    Returns configurable fixed scores so the spike benchmark can measure
    pipeline overhead without a real model.  Default is None (unknown) so the
    UntestedEyeMonitor and both_closed check never fire on a missing model.
    """

    def __init__(
        self,
        left_score: Optional[float] = None,
        right_score: Optional[float] = None,
    ) -> None:
        # Default None = no real model installed.
        # UntestedEyeMonitor treats None scores as low-confidence and never
        # sets attention_override=True, preventing the mock from blocking
        # monocular tests by falsely reporting both eyes open every frame.
        self._left  = left_score
        self._right = right_score

    def detect(
        self,
        frame: np.ndarray,
        landmarks_2d: Optional[np.ndarray],
        bbox: Optional[Tuple[int, int, int, int]],
    ) -> dict:
        # Still execute the crop logic so the benchmark measures realistic CPU
        if landmarks_2d is not None and bbox is not None:
            crop_eye_patches(frame, landmarks_2d, bbox)
        return self._make_result(self._left, self._right)


# ---------------------------------------------------------------------------
# TFLite detector stub  (to be completed in Objective 1)
# ---------------------------------------------------------------------------

class TFLiteEyeClosureDetector(EyeClosureDetector):
    """
    Eye-closure detector backed by an int8 TFLite binary classifier.

    TODO (Objective 1) — complete this class after the Objective 4 spike
    acceptance criteria are confirmed on Pi 4 hardware.

    Model requirements
    ------------------
    - Format   : TFLite int8 (post-training quantisation)
    - Input    : [1, 32, 32, 1] float32 normalised [0, 1]
    - Output   : [1, 1] float32  (probability that the eye is OPEN)
    - Latency  : ≤ 4 ms per inference on Pi 4 (2 eyes = ≤ 8 ms total)

    Candidate model
    ---------------
    MobileNetV3-Small fine-tuned on the MRL Eye Dataset:
      https://mrl.cs.vsb.cz/eyedataset
    After selecting and training, place the .tflite file at:
      backend/models/eye_closure_int8.tflite

    Quantisation note
    -----------------
    Use full-integer (int8) quantisation with a representative dataset
    (1000+ frames from the MRL dataset covering indoor lighting conditions).
    fp16 quantisation is NOT sufficient — int8 gives 2× speedup on Pi 4's
    Cortex-A72 via ARM NEON SIMD.
    """

    def __init__(self, model_path: str) -> None:
        try:
            import tflite_runtime.interpreter as tflite
        except ImportError:
            raise RuntimeError(
                "tflite_runtime not installed.  On Pi OS: "
                "pip install tflite-runtime"
            )

        self._interp = tflite.Interpreter(model_path=model_path, num_threads=1)
        self._interp.allocate_tensors()
        self._input_idx  = self._interp.get_input_details()[0]["index"]
        self._output_idx = self._interp.get_output_details()[0]["index"]

    def detect(
        self,
        frame: np.ndarray,
        landmarks_2d: Optional[np.ndarray],
        bbox: Optional[Tuple[int, int, int, int]],
    ) -> dict:
        if landmarks_2d is None or bbox is None:
            return self._make_result(None, None)

        right_patch, left_patch = crop_eye_patches(frame, landmarks_2d, bbox)

        right_score = self._infer(right_patch)
        left_score  = self._infer(left_patch)

        return self._make_result(left_score, right_score)

    def _infer(self, patch: Optional[np.ndarray]) -> Optional[float]:
        if patch is None:
            return None
        inp = patch[np.newaxis, ...]               # (1, 32, 32, 1)
        self._interp.set_tensor(self._input_idx, inp)
        self._interp.invoke()
        return float(self._interp.get_tensor(self._output_idx)[0, 0])
