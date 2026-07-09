// ---- Types for NadiVision ----

export type AppScreen =
    | "landing"
    | "calibration"
    | "ipd"
    | "mobile-calibration"
    | "camera-setup"
    | "test"
    | "results";

export type StabilityState = "LOCKED" | "STABILIZING" | "UNLOCKED";

export type EDirection = "up" | "down" | "left" | "right";
export type OptotypeType = "tumbling-e" | "landolt-c";

export interface CheatFlag {
    type: "fullscreen_exit" | "tab_switch" | "face_lost" | "multiple_faces" | "fast_answer" | "distance_jump";
    timestamp: number;
    detail?: string;
}

// LogMAR acuity levels (standard clinical progression)
export interface AcuityLevel {
    logMAR: number;
    snellen: string;
    arcMinPerStroke: number; // arcminutes per stroke of the E
    trialsPerLevel: number;
}

export interface TestResponse {
    level: AcuityLevel;
    trialIndex: number;
    presented: EDirection;
    answered: EDirection | null;
    correct: boolean;
    timestamp: number;
    distance: number;
}

export interface TestResult {
    acuitySnellen: string;
    acuityLogMAR: number;
    fractionalLogMAR: number;
    confidenceInterval: { lower: number; upper: number; confidence: number };
    responses: TestResponse[];
    testDistance: number;
    testDuration: number; // ms
    date: string;
    perLevelScores: { level: AcuityLevel; correct: number; total: number }[];
    cheatingFlags: CheatFlag[];
}

export interface CalibrationData {
    mmPerPx: number; // physical mm per CSS pixel
    deviceLabel: string;
    calibratedAt: number;
}

export interface DistanceMeasurement {
    raw: number; // meters
    filtered: number; // meters (after Kalman)
    confidence: number; // 0-1
    method: "iris" | "ipd" | "face_width" | "fused";
    timestamp: number;
}
