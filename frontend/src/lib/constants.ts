import type { AcuityLevel } from "./types";

// Standard LogMAR acuity levels (clinical progression)
export const ACUITY_LEVELS: AcuityLevel[] = [
    { logMAR: 1.0, snellen: "20/200", arcMinPerStroke: 10, trialsPerLevel: 5 },
    { logMAR: 0.7, snellen: "20/100", arcMinPerStroke: 5, trialsPerLevel: 5 },
    { logMAR: 0.5, snellen: "20/63", arcMinPerStroke: 3.162, trialsPerLevel: 5 },
    { logMAR: 0.3, snellen: "20/40", arcMinPerStroke: 2, trialsPerLevel: 5 },
    { logMAR: 0.2, snellen: "20/32", arcMinPerStroke: 1.585, trialsPerLevel: 5 },
    { logMAR: 0.1, snellen: "20/25", arcMinPerStroke: 1.259, trialsPerLevel: 5 },
    { logMAR: 0.0, snellen: "20/20", arcMinPerStroke: 1, trialsPerLevel: 5 },
    { logMAR: -0.1, snellen: "20/16", arcMinPerStroke: 0.794, trialsPerLevel: 5 },
];

// The Tumbling E has 5 strokes tall (each stroke = arcMinPerStroke)
export const E_STROKES = 5;

// Stability guard thresholds
export const STABILITY_DISTANCE_THRESHOLD_CM = 5; // cm
export const STABILITY_GYRO_THRESHOLD_DEG_S = 3; // deg/s
export const STABILITY_LOCK_DURATION_S = 3; // seconds to hold still

// Distance measurement
export const DEFAULT_IPD_MM = 63;
export const IRIS_DIAMETER_MM = 11.7;
export const AVG_FACE_WIDTH_MM = 140;

// Min correct per level to advance
export const MIN_CORRECT_TO_ADVANCE = 3; // out of 5 (ETDRS standard)
// Max wrong per level to terminate
export const MAX_WRONG_TO_TERMINATE = 3; // out of 5

// Ceiling LogMAR for fractional scoring (represents "can't see worst line")
export const LOGMAR_CEILING = 1.3;

// Directions for the Tumbling E
export const DIRECTIONS: ("up" | "down" | "left" | "right")[] = [
    "up",
    "down",
    "left",
    "right",
];
