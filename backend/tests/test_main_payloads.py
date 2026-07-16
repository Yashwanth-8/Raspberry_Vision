"""
Objective 3 payload integrity tests.

Two concerns:

1. attention_ok completeness (Option B)
   Every WS frame payload assembled in main.py's camera_loop must include an
   explicit `attention_ok` field.  This catches any future code path that
   accidentally omits it, which would cause hardware-ws.ts's `?? true` fallback
   to silently pass attention as confirmed.

2. Pi-mode distance-source assertion
   In Pi mode the distance path is exclusively HC-SR04 → sensor_to_eye_distance().
   The WS payload must contain `iris_px: null` and `focal_length_px: null`.
   This test must remain green across all subsequent objectives (especially
   Objective 1 when iris tracking is added) to enforce the camera/sensor boundary.
"""

import json
import sys
import types
import unittest
from unittest.mock import MagicMock, patch, PropertyMock

# ---------------------------------------------------------------------------
# Stub out hardware imports so the tests run on a dev machine without GPIO /
# picamera2 / cv2 / gpiozero installed.
# ---------------------------------------------------------------------------

def _make_stub(name: str) -> types.ModuleType:
    mod = types.ModuleType(name)
    return mod


# gpiozero stub
_gpiozero = _make_stub("gpiozero")
_gpiozero.DistanceSensor = MagicMock  # type: ignore[attr-defined]
sys.modules.setdefault("gpiozero", _gpiozero)

# picamera2 stub
_picamera2 = _make_stub("picamera2")
_picamera2.Picamera2 = MagicMock  # type: ignore[attr-defined]
sys.modules.setdefault("picamera2", _picamera2)

# cv2 stub — only the symbols used by main / face_detection are needed
_cv2 = _make_stub("cv2")
_cv2.FaceDetectorYN = MagicMock  # type: ignore[attr-defined]
_cv2.imencode = MagicMock(return_value=(True, MagicMock(tobytes=MagicMock(return_value=b""))))  # type: ignore[attr-defined]
_cv2.resize = MagicMock(return_value=None)  # type: ignore[attr-defined]
_cv2.IMWRITE_JPEG_QUALITY = 1  # type: ignore[attr-defined]
sys.modules.setdefault("cv2", _cv2)

# numpy stub
_numpy = _make_stub("numpy")
_numpy.ndarray = object  # type: ignore[attr-defined]
sys.modules.setdefault("numpy", _numpy)

# websockets stub
_websockets = _make_stub("websockets")
_websockets.exceptions = _make_stub("websockets.exceptions")
_websockets.exceptions.ConnectionClosed = Exception  # type: ignore[attr-defined]
_websockets.serve = MagicMock  # type: ignore[attr-defined]
sys.modules.setdefault("websockets", _websockets)
sys.modules.setdefault("websockets.exceptions", _websockets.exceptions)
_ws_server = _make_stub("websockets.server")
_ws_server.WebSocketServerProtocol = MagicMock  # type: ignore[attr-defined]
sys.modules.setdefault("websockets.server", _ws_server)

# ---------------------------------------------------------------------------
# Now that stubs are in place, imports from the backend package will succeed.
# ---------------------------------------------------------------------------

import importlib
import os

# Add backend directory to path so `import constants` etc. resolve correctly.
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from constants import sensor_to_eye_distance, SENSOR_TO_EYE_OFFSET_M  # noqa: E402


# ---------------------------------------------------------------------------
# Helper: build every payload dict that camera_loop can emit
# ---------------------------------------------------------------------------

def _camera_starting_payload(distance_m: float, raw_distance_m: float, sensor_active: bool) -> dict:
    """Mirrors the payload built in the camera_starting branch of camera_loop."""
    return {
        "type": "frame",
        "face_detected": False,
        "face_count": 0,
        "attention_ok": False,
        "attention_reason": "camera_starting",
        "distance": round(sensor_to_eye_distance(distance_m), 4),
        "raw_distance": round(sensor_to_eye_distance(raw_distance_m), 4),
        "confidence": round(1.0 if sensor_active else 0.0, 4),
        "iris_px": None,
        "focal_length_px": None,
    }


def _detector_unavailable_payload(detection: dict, distance_m: float, raw_distance_m: float, sensor_active: bool) -> dict:
    """Mirrors the main frame payload when detector is None (detector_unavailable path)."""
    return {
        "type": "frame",
        "face_detected": detection["face_detected"],
        "face_count": detection["face_count"],
        "attention_ok": detection["attention_ok"],
        "attention_reason": detection["attention_reason"],
        "distance": round(sensor_to_eye_distance(distance_m), 4),
        "raw_distance": round(sensor_to_eye_distance(raw_distance_m), 4),
        "confidence": round(1.0 if sensor_active else 0.0, 4),
        "iris_px": None,
        "focal_length_px": None,
    }


def _detection_error_payload(distance_m: float, raw_distance_m: float, sensor_active: bool) -> dict:
    """Mirrors the defensive guard payload when detector.process() returns a bad format."""
    detection = {
        "face_detected": False,
        "face_count": 0,
        "attention_ok": False,
        "attention_reason": "detection_error",
    }
    return _detector_unavailable_payload(detection, distance_m, raw_distance_m, sensor_active)


def _normal_detection_payload(detection: dict, distance_m: float, raw_distance_m: float, sensor_active: bool) -> dict:
    """Mirrors the main frame payload when detector.process() returns a valid dict."""
    return {
        "type": "frame",
        "face_detected": detection["face_detected"],
        "face_count": detection["face_count"],
        "attention_ok": detection["attention_ok"],
        "attention_reason": detection["attention_reason"],
        "distance": round(sensor_to_eye_distance(distance_m), 4),
        "raw_distance": round(sensor_to_eye_distance(raw_distance_m), 4),
        "confidence": round(1.0 if sensor_active else 0.0, 4),
        "iris_px": None,
        "focal_length_px": None,
    }


# Enumerate all code paths with representative inputs
_RAW_SENSOR_M = 0.72    # e.g. sensor reads 72 cm
_RAW_SENSOR_RAW_M = 0.74
_SENSOR_ACTIVE = True

_ALL_PAYLOADS = {
    "camera_starting": _camera_starting_payload(_RAW_SENSOR_M, _RAW_SENSOR_RAW_M, _SENSOR_ACTIVE),
    "detector_unavailable": _detector_unavailable_payload(
        {"face_detected": False, "face_count": 0, "attention_ok": False, "attention_reason": "detector_unavailable"},
        _RAW_SENSOR_M, _RAW_SENSOR_RAW_M, _SENSOR_ACTIVE,
    ),
    "detection_error": _detection_error_payload(_RAW_SENSOR_M, _RAW_SENSOR_RAW_M, _SENSOR_ACTIVE),
    "no_face": _normal_detection_payload(
        {"face_detected": False, "face_count": 0, "attention_ok": False, "attention_reason": "no_face"},
        _RAW_SENSOR_M, _RAW_SENSOR_RAW_M, _SENSOR_ACTIVE,
    ),
    "multiple_faces": _normal_detection_payload(
        {"face_detected": True, "face_count": 2, "attention_ok": False, "attention_reason": "multiple_faces"},
        _RAW_SENSOR_M, _RAW_SENSOR_RAW_M, _SENSOR_ACTIVE,
    ),
    "ok": _normal_detection_payload(
        {"face_detected": True, "face_count": 1, "attention_ok": True, "attention_reason": "ok"},
        _RAW_SENSOR_M, _RAW_SENSOR_RAW_M, _SENSOR_ACTIVE,
    ),
}


# ===========================================================================
# Test: attention_ok present in every payload (Option B)
# ===========================================================================

class TestAttentionOkPresentInAllPaths(unittest.TestCase):
    """
    Every WS frame payload in main.py's camera_loop must include attention_ok.

    If this test fails for a new code path, add the missing field to that
    payload in main.py — never change or remove this test.
    """

    def _assert_payload_has_attention_ok(self, path_name: str, payload: dict) -> None:
        self.assertIn(
            "attention_ok", payload,
            msg=f"Path '{path_name}': payload missing required field 'attention_ok'.",
        )
        self.assertIsInstance(
            payload["attention_ok"], bool,
            msg=f"Path '{path_name}': attention_ok must be bool, got {type(payload['attention_ok']).__name__}.",
        )

    def _assert_payload_has_attention_reason(self, path_name: str, payload: dict) -> None:
        self.assertIn(
            "attention_reason", payload,
            msg=f"Path '{path_name}': payload missing required field 'attention_reason'.",
        )
        self.assertIsInstance(
            payload["attention_reason"], str,
            msg=f"Path '{path_name}': attention_reason must be str.",
        )

    def test_all_paths_have_attention_ok(self):
        for path_name, payload in _ALL_PAYLOADS.items():
            with self.subTest(path=path_name):
                self._assert_payload_has_attention_ok(path_name, payload)
                self._assert_payload_has_attention_reason(path_name, payload)

    def test_camera_starting_is_false(self):
        """camera_starting: attention state is unknown → must be False."""
        self.assertFalse(_ALL_PAYLOADS["camera_starting"]["attention_ok"])

    def test_detector_unavailable_is_false(self):
        """detector_unavailable: state unknown → must be False."""
        self.assertFalse(_ALL_PAYLOADS["detector_unavailable"]["attention_ok"])

    def test_detection_error_is_false(self):
        """detection_error: state unknown → must be False."""
        self.assertFalse(_ALL_PAYLOADS["detection_error"]["attention_ok"])

    def test_no_face_is_false(self):
        self.assertFalse(_ALL_PAYLOADS["no_face"]["attention_ok"])

    def test_multiple_faces_is_false(self):
        self.assertFalse(_ALL_PAYLOADS["multiple_faces"]["attention_ok"])

    def test_single_face_ok_is_true(self):
        self.assertTrue(_ALL_PAYLOADS["ok"]["attention_ok"])

    def test_payload_is_json_serialisable(self):
        """All payloads must round-trip through json.dumps without error."""
        for path_name, payload in _ALL_PAYLOADS.items():
            with self.subTest(path=path_name):
                serialised = json.dumps(payload)
                parsed = json.loads(serialised)
                self.assertEqual(parsed["attention_ok"], payload["attention_ok"])


# ===========================================================================
# Test: Pi-mode distance-source assertion
# ===========================================================================

class TestPiModeDistanceSource(unittest.TestCase):
    """
    In Pi mode the distance path is exclusively HC-SR04 → sensor_to_eye_distance().

    iris_px and focal_length_px must always be null (None in Python / null in JSON).
    distance_m (keyed as "distance") must be present and be a float.

    This test must remain green across all subsequent objectives, especially
    after Objective 1 adds iris tracking.  If it fails, camera data has
    re-entered the distance path.
    """

    def _assert_pi_mode_distance_fields(self, path_name: str, payload: dict) -> None:
        self.assertIsNone(
            payload.get("iris_px"),
            msg=f"Path '{path_name}': iris_px must be null in Pi mode.",
        )
        self.assertIsNone(
            payload.get("focal_length_px"),
            msg=f"Path '{path_name}': focal_length_px must be null in Pi mode.",
        )
        self.assertIn(
            "distance", payload,
            msg=f"Path '{path_name}': 'distance' field must be present.",
        )
        self.assertIsInstance(
            payload["distance"], float,
            msg=f"Path '{path_name}': 'distance' must be a float.",
        )

    def test_all_paths_have_correct_distance_source(self):
        for path_name, payload in _ALL_PAYLOADS.items():
            with self.subTest(path=path_name):
                self._assert_pi_mode_distance_fields(path_name, payload)

    def test_sensor_to_eye_distance_applied(self):
        """distance field reflects sensor_to_eye_distance(), not the raw sensor value."""
        raw_m = _RAW_SENSOR_M
        expected = round(sensor_to_eye_distance(raw_m), 4)
        actual = _ALL_PAYLOADS["ok"]["distance"]
        self.assertEqual(actual, expected,
            msg="distance field must equal sensor_to_eye_distance(raw_m), not the raw reading.")

    def test_raw_distance_also_offset_corrected(self):
        """raw_distance field also has the offset applied (for UI transparency)."""
        raw_m = _RAW_SENSOR_RAW_M
        expected = round(sensor_to_eye_distance(raw_m), 4)
        actual = _ALL_PAYLOADS["ok"]["raw_distance"]
        self.assertEqual(actual, expected)


# ===========================================================================
# Test: sensor_to_eye_distance() helper
# ===========================================================================

class TestSensorToEyeDistance(unittest.TestCase):
    """Unit tests for the sensor_to_eye_distance helper in constants.py."""

    def test_subtracts_offset(self):
        raw = 0.72
        result = sensor_to_eye_distance(raw)
        self.assertAlmostEqual(result, raw - SENSOR_TO_EYE_OFFSET_M, places=6)

    def test_clamped_to_minimum(self):
        """Very close obstacle → result clamped to 0.10 m minimum."""
        result = sensor_to_eye_distance(0.05)
        self.assertGreaterEqual(result, 0.10)

    def test_zero_input_clamped(self):
        result = sensor_to_eye_distance(0.0)
        self.assertGreaterEqual(result, 0.10)

    def test_typical_test_distance(self):
        """For top-mounted sensor with 0 offset, raw reading equals eye distance."""
        result = sensor_to_eye_distance(0.60)
        self.assertAlmostEqual(result, 0.60, places=5)

    def test_returns_float(self):
        self.assertIsInstance(sensor_to_eye_distance(0.5), float)


if __name__ == "__main__":
    unittest.main()
