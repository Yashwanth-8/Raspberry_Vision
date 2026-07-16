# Port of src/lib/constants.ts — shared constants for distance estimation and test logic

ACUITY_LEVELS = [
    {"logMAR": 1.0,  "snellen": "20/200", "arcMinPerStroke": 10.0,   "trialsPerLevel": 5},
    {"logMAR": 0.7,  "snellen": "20/100", "arcMinPerStroke": 5.0,    "trialsPerLevel": 5},
    {"logMAR": 0.5,  "snellen": "20/63",  "arcMinPerStroke": 3.162,  "trialsPerLevel": 5},
    {"logMAR": 0.3,  "snellen": "20/40",  "arcMinPerStroke": 2.0,    "trialsPerLevel": 5},
    {"logMAR": 0.2,  "snellen": "20/32",  "arcMinPerStroke": 1.585,  "trialsPerLevel": 5},
    {"logMAR": 0.1,  "snellen": "20/25",  "arcMinPerStroke": 1.259,  "trialsPerLevel": 5},
    {"logMAR": 0.0,  "snellen": "20/20",  "arcMinPerStroke": 1.0,    "trialsPerLevel": 5},
    {"logMAR": -0.1, "snellen": "20/16",  "arcMinPerStroke": 0.794,  "trialsPerLevel": 5},
]

E_STROKES = 5

STABILITY_DISTANCE_THRESHOLD_CM = 5
STABILITY_LOCK_DURATION_S = 3

DEFAULT_IPD_MM = 63.0
IRIS_DIAMETER_MM = 11.7
AVG_FACE_WIDTH_MM = 140.0

MIN_CORRECT_TO_ADVANCE = 3
MAX_WRONG_TO_TERMINATE = 3
LOGMAR_CEILING = 1.3

DIRECTIONS = ["up", "down", "left", "right"]

# WebSocket server config
WS_HOST = "0.0.0.0"
WS_PORT = 8765

# Pi Camera config
# Capture at 720p; detection canvas (320×240) is produced by resizing in camera.py
CAMERA_WIDTH = 1280
CAMERA_HEIGHT = 720
CAMERA_FRAMERATE = 30
DETECT_WIDTH = 320
DETECT_HEIGHT = 240

# HC-SR04 ultrasonic sensor GPIO pins (BCM numbering)
ULTRASONIC_TRIGGER_PIN = 23
ULTRASONIC_ECHO_PIN = 24

# ---------------------------------------------------------------------------
# Sensor-to-eye offset
# ---------------------------------------------------------------------------
# The HC-SR04 is mounted ON TOP OF the screen, pointing forward toward the patient.
#
# Geometry:
#   At typical test distances (40–80 cm) the sensor reading closely approximates
#   the horizontal screen-to-eye distance. The only geometric error comes from
#   the sensor being above the patient's eye level (≈ half the screen height).
#   For a 20 cm screen this error is only ~1–3 cm — within the ±2–3 cm residual
#   uncertainty from the lack of a chin rest. A linear offset is sufficient.
#
# Measurement method (do once on the physical rig):
#   1. Position a patient at a known distance (tape measure, eye to screen face).
#   2. Read what the sensor reports in the app's live distance display.
#   3. SENSOR_TO_EYE_OFFSET_M = sensor_reading − actual_eye_distance
#      (positive if sensor reads MORE than actual, negative if it reads LESS)
#   Typical value for top-mounted sensor: 0.00 – 0.03 m (0 – 3 cm).
#
# Start at 0.0 and refine with the empirical measurement above.
# *** Update before clinical use. ***
SENSOR_TO_EYE_OFFSET_M: float = 0.0    # metres — update after empirical measurement


def sensor_to_eye_distance(raw_m: float) -> float:
    """
    Convert a raw HC-SR04 reading to screen-to-eye distance.

    For a top-of-screen sensor the raw reading closely approximates the
    horizontal screen-to-eye distance.  Subtracts the empirically measured
    SENSOR_TO_EYE_OFFSET_M (typically 0–3 cm for top-mounted placement) and
    clamps to a minimum of 10 cm.

    This is the single canonical application point for the offset; no other
    code path should apply it.
    """
    corrected = raw_m - SENSOR_TO_EYE_OFFSET_M
    return max(corrected, 0.10)
