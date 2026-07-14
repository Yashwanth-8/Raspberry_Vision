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
# main stream → 720p RGB888, sent as JPEG preview to the frontend
# lores stream → 320×240 YUV420, fed into YuNet for attention detection
CAMERA_WIDTH = 1280
CAMERA_HEIGHT = 720
CAMERA_FRAMERATE = 30
DETECT_WIDTH = 320
DETECT_HEIGHT = 240

# HC-SR04 ultrasonic sensor GPIO pins (BCM numbering)
ULTRASONIC_TRIGGER_PIN = 23
ULTRASONIC_ECHO_PIN = 24

# Attention-monitoring rules
FACE_CENTRE_TOLERANCE = 0.25   # face cx must be within 25% of frame width from centre
FACE_FORWARD_EYE_RATIO = 0.45  # eye separation must be > 45% of face bbox width
                                # (catches ~30° head turns; 0.30 only caught ~60°)
