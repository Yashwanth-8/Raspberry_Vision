import type { AcuityLevel } from "./types";

// Full ETDRS acuity chart — 14 lines, uniform 0.1 LogMAR steps
// arcMinPerStroke = 10^logMAR  (exact pinhole formula per ISO 8596)
export const ACUITY_LEVELS: AcuityLevel[] = [
    { logMAR: 1.0, snellen: "20/200", arcMinPerStroke: 10.000, trialsPerLevel: 5 },
    { logMAR: 0.9, snellen: "20/160", arcMinPerStroke: 7.943, trialsPerLevel: 5 },
    { logMAR: 0.8, snellen: "20/125", arcMinPerStroke: 6.310, trialsPerLevel: 5 },
    { logMAR: 0.7, snellen: "20/100", arcMinPerStroke: 5.012, trialsPerLevel: 5 },
    { logMAR: 0.6, snellen: "20/80", arcMinPerStroke: 3.981, trialsPerLevel: 5 },
    { logMAR: 0.5, snellen: "20/63", arcMinPerStroke: 3.162, trialsPerLevel: 5 },
    { logMAR: 0.4, snellen: "20/50", arcMinPerStroke: 2.512, trialsPerLevel: 5 },
    { logMAR: 0.3, snellen: "20/40", arcMinPerStroke: 1.995, trialsPerLevel: 5 },
    { logMAR: 0.2, snellen: "20/32", arcMinPerStroke: 1.585, trialsPerLevel: 5 },
    { logMAR: 0.1, snellen: "20/25", arcMinPerStroke: 1.259, trialsPerLevel: 5 },
    { logMAR: 0.0, snellen: "20/20", arcMinPerStroke: 1.000, trialsPerLevel: 5 },
    { logMAR: -0.1, snellen: "20/16", arcMinPerStroke: 0.794, trialsPerLevel: 5 },
    { logMAR: -0.2, snellen: "20/12.5", arcMinPerStroke: 0.631, trialsPerLevel: 5 },
    { logMAR: -0.3, snellen: "20/10", arcMinPerStroke: 0.501, trialsPerLevel: 5 },
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

// Min correct per level to advance (ETDRS: 3 of 5)
export const MIN_CORRECT_TO_ADVANCE = 3;
// Max wrong per level to terminate early
export const MAX_WRONG_TO_TERMINATE = 3;

// ETDRS LogMAR ceiling = worst tested line (1.0) + one 0.1 step
// Formula: acuity = 1.1 − 0.02 × totalCorrectLetters  (Ferris et al. 1982)
export const LOGMAR_CEILING = 1.1;

// Maximum ETDRS letter score: 14 lines × 5 letters
export const MAX_ETDRS_LETTERS = 70;

// Directions for the Tumbling E
export const DIRECTIONS: ("up" | "down" | "left" | "right")[] = [
    "up",
    "down",
    "left",
    "right",
];
