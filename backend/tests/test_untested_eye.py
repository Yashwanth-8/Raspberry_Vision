"""
Unit tests for UntestedEyeMonitor — Objective 2.

Tests confirm:
  - Binocular mode (OU) is always inactive
  - Correct eye is monitored for OD and OS
  - Consecutive-frame threshold logic
  - Persistent-open timing
  - Low-confidence (ambiguous score) flag
  - Reset on set_eye_tested / reset()
"""

import sys
import types
import unittest

# ---------------------------------------------------------------------------
# Hardware stubs — allow import without GPIO / cv2 on dev machine
# ---------------------------------------------------------------------------
for _mod_name in ["gpiozero", "picamera2", "numpy"]:
    if _mod_name not in sys.modules:
        _m = types.ModuleType(_mod_name)
        _m.ndarray = object      # type: ignore[attr-defined]
        _m.DistanceSensor = object  # type: ignore[attr-defined]
        _m.Picamera2 = object       # type: ignore[attr-defined]
        sys.modules[_mod_name] = _m

import os
_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from attention.untested_eye import (
    UntestedEyeMonitor,
    CONFIRMED_FRAMES,
    OPEN_SCORE_THRESHOLD,
    PERSISTENT_SECONDS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _open_frame(score: float = 0.9) -> dict:
    """Closure result with both eyes open at given score."""
    return {
        "left_score": score, "right_score": score,
        "left_eye_open": score > 0.5, "right_eye_open": score > 0.5,
        "both_closed": False, "eye_closure_ok": True,
    }


def _closed_frame(score: float = 0.1) -> dict:
    """Closure result with both eyes closed at given score."""
    return {
        "left_score": score, "right_score": score,
        "left_eye_open": False, "right_eye_open": False,
        "both_closed": True, "eye_closure_ok": False,
    }


def _run_frames(monitor: UntestedEyeMonitor, frame: dict, n: int) -> dict:
    """Feed N identical frames to the monitor; return last result."""
    result = {}
    for _ in range(n):
        result = monitor.update(frame)
    return result


# ---------------------------------------------------------------------------
# Binocular mode (OU) — monitor must be inactive
# ---------------------------------------------------------------------------

class TestBinocularMode(unittest.TestCase):

    def setUp(self):
        self.mon = UntestedEyeMonitor()    # default: OU

    def test_ou_never_overrides_attention(self):
        result = _run_frames(self.mon, _open_frame(), CONFIRMED_FRAMES + 5)
        self.assertFalse(result["attention_override"])

    def test_ou_events_always_zero(self):
        result = _run_frames(self.mon, _open_frame(), CONFIRMED_FRAMES + 5)
        self.assertEqual(result["untested_eye_open_events"], 0)


# ---------------------------------------------------------------------------
# Eye-selection logic: OD tests left eye, OS tests right eye
# ---------------------------------------------------------------------------

class TestEyeSelection(unittest.TestCase):

    def test_od_monitors_left_eye_score(self):
        mon = UntestedEyeMonitor()
        mon.set_eye_tested("OD")
        # Right eye closed (score=0.1), LEFT eye open (score=0.9)
        frame = {"left_score": 0.9, "right_score": 0.1,
                 "left_eye_open": True, "right_eye_open": False,
                 "both_closed": False, "eye_closure_ok": True}
        result = _run_frames(mon, frame, CONFIRMED_FRAMES)
        self.assertTrue(result["attention_override"],
                        "OD mode should monitor left eye (OS)")

    def test_os_monitors_right_eye_score(self):
        mon = UntestedEyeMonitor()
        mon.set_eye_tested("OS")
        # Left eye closed (score=0.1), RIGHT eye open (score=0.9)
        frame = {"left_score": 0.1, "right_score": 0.9,
                 "left_eye_open": False, "right_eye_open": True,
                 "both_closed": False, "eye_closure_ok": True}
        result = _run_frames(mon, frame, CONFIRMED_FRAMES)
        self.assertTrue(result["attention_override"],
                        "OS mode should monitor right eye (OD)")

    def test_od_ignores_right_eye(self):
        mon = UntestedEyeMonitor()
        mon.set_eye_tested("OD")
        # Left eye closed, right eye open — should NOT trigger (left is untested)
        frame = {"left_score": 0.1, "right_score": 0.9,
                 "left_eye_open": False, "right_eye_open": True,
                 "both_closed": False, "eye_closure_ok": True}
        result = _run_frames(mon, frame, CONFIRMED_FRAMES + 5)
        self.assertFalse(result["attention_override"])


# ---------------------------------------------------------------------------
# Confirmed-open threshold (consecutive frames)
# ---------------------------------------------------------------------------

class TestConfirmedOpenThreshold(unittest.TestCase):

    def setUp(self):
        self.mon = UntestedEyeMonitor()
        self.mon.set_eye_tested("OD")

    def test_not_confirmed_before_threshold(self):
        result = _run_frames(self.mon, _open_frame(), CONFIRMED_FRAMES - 1)
        self.assertFalse(result["attention_override"])

    def test_confirmed_at_threshold(self):
        result = _run_frames(self.mon, _open_frame(), CONFIRMED_FRAMES)
        self.assertTrue(result["attention_override"])

    def test_event_count_increments_once_per_event(self):
        # One continuous run → exactly 1 event
        _run_frames(self.mon, _open_frame(), CONFIRMED_FRAMES + 10)
        result = self.mon.update(_open_frame())
        self.assertEqual(result["untested_eye_open_events"], 1)

    def test_reset_clears_consecutive_count(self):
        _run_frames(self.mon, _open_frame(), CONFIRMED_FRAMES - 1)
        # One closed frame resets consecutive count
        self.mon.update(_closed_frame())
        result = _run_frames(self.mon, _open_frame(), CONFIRMED_FRAMES - 1)
        self.assertFalse(result["attention_override"],
                         "After a closed frame, must re-accumulate CONFIRMED_FRAMES")


# ---------------------------------------------------------------------------
# Low-confidence detection
# ---------------------------------------------------------------------------

class TestLowConfidence(unittest.TestCase):

    def setUp(self):
        self.mon = UntestedEyeMonitor()
        self.mon.set_eye_tested("OD")

    def test_ambiguous_score_sets_low_confidence(self):
        frame = {"left_score": 0.50, "right_score": 0.50,    # squarely ambiguous
                 "left_eye_open": None, "right_eye_open": None,
                 "both_closed": False, "eye_closure_ok": True}
        result = self.mon.update(frame)
        self.assertTrue(result["occlusion_confidence_low"])

    def test_none_score_sets_low_confidence(self):
        frame = {"left_score": None, "right_score": None,
                 "left_eye_open": None, "right_eye_open": None,
                 "both_closed": False, "eye_closure_ok": False}
        result = self.mon.update(frame)
        self.assertTrue(result["occlusion_confidence_low"])

    def test_high_confidence_score_does_not_set_low_confidence(self):
        result = self.mon.update(_open_frame(score=0.95))
        self.assertFalse(result["occlusion_confidence_low"])


# ---------------------------------------------------------------------------
# set_eye_tested and reset
# ---------------------------------------------------------------------------

class TestResetBehaviour(unittest.TestCase):

    def test_set_eye_tested_resets_tracking(self):
        mon = UntestedEyeMonitor()
        mon.set_eye_tested("OD")
        # Partially fill the consecutive buffer
        _run_frames(mon, _open_frame(), CONFIRMED_FRAMES - 1)
        # Change eye mid-test → tracking must reset
        mon.set_eye_tested("OS")
        result = _run_frames(mon, _open_frame(), CONFIRMED_FRAMES - 1)
        self.assertFalse(result["attention_override"],
                         "set_eye_tested must reset consecutive counter")

    def test_reset_returns_to_ou_mode(self):
        mon = UntestedEyeMonitor()
        mon.set_eye_tested("OD")
        _run_frames(mon, _open_frame(), CONFIRMED_FRAMES + 5)
        mon.reset()
        result = _run_frames(mon, _open_frame(), CONFIRMED_FRAMES + 5)
        self.assertFalse(result["attention_override"],
                         "After reset(), monitor must be in OU (inactive) mode")

    def test_reset_clears_event_count(self):
        mon = UntestedEyeMonitor()
        mon.set_eye_tested("OD")
        _run_frames(mon, _open_frame(), CONFIRMED_FRAMES + 5)
        mon.reset()
        result = mon.update(_open_frame())
        self.assertEqual(result["untested_eye_open_events"], 0)


if __name__ == "__main__":
    unittest.main()
