import { create } from "zustand";
import type {
    AppScreen,
    StabilityState,
    CalibrationData,
    TestResponse,
    AcuityLevel,
    EDirection,
    TestResult,
    OptotypeType,
} from "./types";
import { ACUITY_LEVELS } from "./constants";

interface AppState {
    // Navigation
    screen: AppScreen;
    setScreen: (s: AppScreen) => void;

    // Calibration
    calibration: CalibrationData | null;
    setCalibration: (c: CalibrationData) => void;

    // IPD
    ipd: number; // mm
    setIpd: (v: number) => void;

    // Mobile calibration
    focalLengthPx: number; // arm's-length calibrated focal length (0 = not calibrated)
    setFocalLengthPx: (v: number) => void;
    isMobile: boolean;
    setIsMobile: (v: boolean) => void;

    // Optotype type
    optotypeType: OptotypeType;
    setOptotypeType: (t: OptotypeType) => void;

    // Distance
    distance: number; // meters, filtered
    rawDistance: number;
    distanceConfidence: number;
    setDistance: (d: number, raw: number, confidence: number) => void;

    // Stability
    stability: StabilityState;
    setStability: (s: StabilityState) => void;
    lockedDistance: number;
    setLockedDistance: (d: number) => void;
    stabilityTimer: number; // seconds remaining
    setStabilityTimer: (t: number) => void;

    // Test state
    currentLevelIndex: number;
    currentTrialIndex: number;
    currentDirection: EDirection;
    responses: TestResponse[];
    testStartTime: number;
    setCurrentLevel: (i: number) => void;
    setCurrentTrial: (i: number) => void;
    setCurrentDirection: (d: EDirection) => void;
    addResponse: (r: TestResponse) => void;
    setTestStartTime: (t: number) => void;

    // Results
    testResult: TestResult | null;
    setTestResult: (r: TestResult) => void;

    // Reset
    resetTest: () => void;
}

export const useAppStore = create<AppState>((set) => ({
    screen: "landing",
    setScreen: (screen) => set({ screen }),

    calibration: null,
    setCalibration: (calibration) => set({ calibration }),

    ipd: 63,
    setIpd: (ipd) => set({ ipd }),

    focalLengthPx: 0,
    setFocalLengthPx: (focalLengthPx) => set({ focalLengthPx }),
    isMobile: false,
    setIsMobile: (isMobile) => set({ isMobile }),

    optotypeType: "tumbling-e",
    setOptotypeType: (optotypeType) => set({ optotypeType }),

    distance: 0,
    rawDistance: 0,
    distanceConfidence: 0,
    setDistance: (distance, rawDistance, distanceConfidence) =>
        set({ distance, rawDistance, distanceConfidence }),

    stability: "LOCKED",
    setStability: (stability) => set({ stability }),
    lockedDistance: 0,
    setLockedDistance: (lockedDistance) => set({ lockedDistance }),
    stabilityTimer: 3,
    setStabilityTimer: (stabilityTimer) => set({ stabilityTimer }),

    currentLevelIndex: 0,
    currentTrialIndex: 0,
    currentDirection: "right",
    responses: [],
    testStartTime: 0,
    setCurrentLevel: (currentLevelIndex) => set({ currentLevelIndex }),
    setCurrentTrial: (currentTrialIndex) => set({ currentTrialIndex }),
    setCurrentDirection: (currentDirection) => set({ currentDirection }),
    addResponse: (r) => set((s) => ({ responses: [...s.responses, r] })),
    setTestStartTime: (testStartTime) => set({ testStartTime }),

    testResult: null,
    setTestResult: (testResult) => set({ testResult }),

    resetTest: () =>
        set({
            currentLevelIndex: 0,
            currentTrialIndex: 0,
            currentDirection: "right",
            responses: [],
            testStartTime: 0,
            testResult: null,
            stability: "LOCKED",
            lockedDistance: 0,
            stabilityTimer: 3,
        }),
}));
