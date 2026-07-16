"""
Untested-eye open detection for monocular tests — Objective 2 deliverable.

During a monocular test (eye_tested = "OD" or "OS"), this monitor checks
whether the non-tested eye appears clearly open.  If it is confirmed open for
CONFIRMED_FRAMES consecutive frames, the pipeline emits attention_ok=False with
attention_reason="untested_eye_open" to pause the test.

Eye mapping
-----------
  OD (right eye tested)  →  monitor OS: left_score  from EyeClosureDetector
  OS (left eye tested)   →  monitor OD: right_score
  OU (binocular)         →  monitor inactive; all fields return safe defaults

Response tiers
--------------
  Confirmed open  : consecutive_frames ≥ CONFIRMED_FRAMES
                    → attention_override=True → test paused, prompt shown
  Persistent open : confirmed and open for ≥ PERSISTENT_SECONDS
                    → persistent_open=True → show stronger warning
  Low confidence  : score ∈ [AMBIGUOUS_LO, AMBIGUOUS_HI] or score is None
                    → occlusion_confidence_low=True, trial flagged but not paused

Calibration note
----------------
All threshold constants below should be re-validated on the physical rig with
the real TFLiteEyeClosureDetector.  The defaults below are conservative starting
points for the MockEyeClosureDetector development phase.
"""

import time
from typing import Optional

# ---------------------------------------------------------------------------
# Threshold constants (calibrate against physical rig)
# ---------------------------------------------------------------------------

OPEN_SCORE_THRESHOLD: float = 0.65   # score > this → eye appears open
AMBIGUOUS_ZONE_LO:    float = 0.40   # score ∈ [AMBIG_LO, AMBIG_HI] → low confidence
AMBIGUOUS_ZONE_HI:    float = 0.60
CONFIRMED_FRAMES:     int   = 10     # consecutive frames ≈ 333 ms at 30 fps
PERSISTENT_SECONDS:   float = 2.0    # seconds of confirmed open → persistent flag


class UntestedEyeMonitor:
    """
    Stateful per-test monitor for untested-eye open detection.

    Thread-safety: all state is modified only from within AttentionPipeline.process(),
    which is serialised by the run_in_executor pattern (one call per frame).
    """

    def __init__(self) -> None:
        self._eye_tested:          str           = "OU"
        self._consecutive_open:    int           = 0
        self._open_since:          Optional[float] = None  # monotonic time of first confirmed open
        self._was_confirmed:       bool          = False   # prevents double-counting events
        self._total_open_events:   int           = 0
        self._occlusion_low:       bool          = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_eye_tested(self, eye: str) -> None:
        """
        Set the eye being tested.  Resets all per-trial tracking state.
        Called from handle_client() when a set_test_mode WS message arrives.
        """
        self._eye_tested = eye if eye in ("OD", "OS", "OU") else "OU"
        self._reset()

    def reset(self) -> None:
        """
        Full state reset.  Called on WS reconnect to clear stale trial data
        (the backend defaults to binocular mode on every reconnect).
        """
        self._eye_tested = "OU"
        self._reset()

    def update(self, closure_result: dict) -> dict:
        """
        Process one frame's eye-closure result.

        Parameters
        ----------
        closure_result
            Dict returned by EyeClosureDetector.detect().  Expected keys:
            "left_score", "right_score", "left_eye_open", "right_eye_open".

        Returns
        -------
        dict with keys:
            attention_override         bool  — True → set attention_ok=False
            persistent_open            bool  — True after PERSISTENT_SECONDS
            untested_eye_open_events   int   — cumulative confirmed-open event count
            occlusion_confidence_low   bool  — True when score is ambiguous
        """
        if self._eye_tested == "OU":
            return self._no_op()

        score = self._untested_eye_score(closure_result)

        # Missing crop → low confidence, don't confirm
        if score is None:
            self._occlusion_low = True
            self._consecutive_open = 0
            self._open_since = None
            self._was_confirmed = False
            return self._build_result(confirmed=False)

        # Ambiguous score → flag low confidence
        if AMBIGUOUS_ZONE_LO <= score <= AMBIGUOUS_ZONE_HI:
            self._occlusion_low = True

        if score > OPEN_SCORE_THRESHOLD:
            self._consecutive_open += 1
        else:
            # Eye appears covered or closed — clear consecutive run
            self._consecutive_open = 0
            self._open_since = None
            self._was_confirmed = False
            return self._build_result(confirmed=False)

        confirmed = self._consecutive_open >= CONFIRMED_FRAMES

        if confirmed:
            if not self._was_confirmed:
                self._was_confirmed = True
                self._total_open_events += 1
                self._open_since = time.monotonic()
            persistent = (
                self._open_since is not None
                and (time.monotonic() - self._open_since) >= PERSISTENT_SECONDS
            )
        else:
            persistent = False

        return self._build_result(confirmed=confirmed, persistent=persistent)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _untested_eye_score(self, closure_result: dict) -> Optional[float]:
        """Return the openness score for the non-tested (monitored) eye."""
        if self._eye_tested == "OD":
            # Testing right eye (OD) → monitor left eye (OS)
            return closure_result.get("left_score")
        else:
            # Testing left eye (OS) → monitor right eye (OD)
            return closure_result.get("right_score")

    def _build_result(self, confirmed: bool, persistent: bool = False) -> dict:
        return {
            "attention_override":       confirmed,
            "persistent_open":          persistent,
            "untested_eye_open_events": self._total_open_events,
            "occlusion_confidence_low": self._occlusion_low,
        }

    def _no_op(self) -> dict:
        """Safe defaults when binocular mode is active (eye_tested='OU')."""
        return {
            "attention_override":       False,
            "persistent_open":          False,
            "untested_eye_open_events": 0,
            "occlusion_confidence_low": False,
        }

    def _reset(self) -> None:
        self._consecutive_open  = 0
        self._open_since        = None
        self._was_confirmed     = False
        self._total_open_events = 0
        self._occlusion_low     = False
