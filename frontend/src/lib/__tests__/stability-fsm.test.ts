/**
 * stability-fsm.test.ts
 *
 * Unit tests for stepStabilizing() — the STABILIZING-state tick of the
 * distance-stability FSM.
 *
 * Deliverable 1.X test obligation:
 *   "This change ships with a unit or integration test that exercises the FSM
 *    transition (COUNTING → piAttentionOk: false → LOCKED, countdown reset to
 *    zero). The fix is 2–3 lines; the test is the weight-bearing deliverable."
 */

import { describe, it, expect } from "vitest";
import { stepStabilizing } from "../stability-fsm";
import {
    STABILITY_LOCK_DURATION_S,
    STABILITY_DISTANCE_THRESHOLD_CM,
} from "../constants";

// ---------------------------------------------------------------------------
// Helpers — base inputs for common scenarios
// ---------------------------------------------------------------------------

const BASE_COUNTING: Parameters<typeof stepStabilizing>[0] = {
    distDriftCm: 2,                         // well within threshold
    elapsedSeconds: STABILITY_LOCK_DURATION_S / 2,  // halfway through countdown
    piMode: true,
    piAttentionOk: true,
};

// ---------------------------------------------------------------------------
// Attention-gate tests  (Deliverable 1.X core requirement)
// ---------------------------------------------------------------------------

describe("stepStabilizing — attention gate", () => {
    it("returns reset_attention when piMode=true and piAttentionOk=false mid-countdown", () => {
        // This is the primary Deliverable 1.X case:
        // patient looks away mid-countdown → countdown must be interrupted immediately.
        const result = stepStabilizing({
            ...BASE_COUNTING,
            piMode: true,
            piAttentionOk: false,
        });
        expect(result).toBe("reset_attention");
    });

    it("does NOT return reset_attention when piMode=false (browser / non-Pi mode)", () => {
        // In browser mode there is no backend attention signal; the gate must be inactive.
        const result = stepStabilizing({
            ...BASE_COUNTING,
            piMode: false,
            piAttentionOk: false,   // even if false, gate is inactive without Pi
        });
        expect(result).not.toBe("reset_attention");
    });

    it("returns counting (not reset_attention) when piMode=true and piAttentionOk=true", () => {
        const result = stepStabilizing({
            ...BASE_COUNTING,
            piMode: true,
            piAttentionOk: true,
        });
        expect(result).toBe("counting");
    });

    it("attention check has priority over drift check when both conditions are true", () => {
        // If both attention is lost AND distance drifts, attention fires first.
        const result = stepStabilizing({
            distDriftCm: STABILITY_DISTANCE_THRESHOLD_CM + 5,   // drift also exceeded
            elapsedSeconds: 0.5,
            piMode: true,
            piAttentionOk: false,
        });
        expect(result).toBe("reset_attention");
    });
});

// ---------------------------------------------------------------------------
// Distance-drift tests  (existing behaviour, must remain intact)
// ---------------------------------------------------------------------------

describe("stepStabilizing — distance drift", () => {
    it("returns reset_drift when distance drifts beyond threshold", () => {
        const result = stepStabilizing({
            ...BASE_COUNTING,
            distDriftCm: STABILITY_DISTANCE_THRESHOLD_CM + 1,
        });
        expect(result).toBe("reset_drift");
    });

    it("returns counting when drift is exactly at threshold", () => {
        const result = stepStabilizing({
            ...BASE_COUNTING,
            distDriftCm: STABILITY_DISTANCE_THRESHOLD_CM,
        });
        expect(result).toBe("counting");
    });

    it("returns counting when drift is just below threshold", () => {
        const result = stepStabilizing({
            ...BASE_COUNTING,
            distDriftCm: STABILITY_DISTANCE_THRESHOLD_CM - 0.1,
        });
        expect(result).toBe("counting");
    });
});

// ---------------------------------------------------------------------------
// Countdown completion tests
// ---------------------------------------------------------------------------

describe("stepStabilizing — countdown completion", () => {
    it("returns unlocked when elapsed time reaches STABILITY_LOCK_DURATION_S", () => {
        const result = stepStabilizing({
            ...BASE_COUNTING,
            elapsedSeconds: STABILITY_LOCK_DURATION_S,
        });
        expect(result).toBe("unlocked");
    });

    it("returns unlocked when elapsed time exceeds STABILITY_LOCK_DURATION_S", () => {
        const result = stepStabilizing({
            ...BASE_COUNTING,
            elapsedSeconds: STABILITY_LOCK_DURATION_S + 1,
        });
        expect(result).toBe("unlocked");
    });

    it("returns counting when elapsed is just below STABILITY_LOCK_DURATION_S", () => {
        const result = stepStabilizing({
            ...BASE_COUNTING,
            elapsedSeconds: STABILITY_LOCK_DURATION_S - 0.01,
        });
        expect(result).toBe("counting");
    });
});

// ---------------------------------------------------------------------------
// Priority ordering tests
// ---------------------------------------------------------------------------

describe("stepStabilizing — priority ordering", () => {
    it("attention check has priority over countdown completion", () => {
        // Even if countdown is complete, attention failure fires first.
        const result = stepStabilizing({
            distDriftCm: 0,
            elapsedSeconds: STABILITY_LOCK_DURATION_S + 1,   // countdown done
            piMode: true,
            piAttentionOk: false,                           // attention lost
        });
        expect(result).toBe("reset_attention");
    });

    it("drift check has priority over countdown completion", () => {
        const result = stepStabilizing({
            distDriftCm: STABILITY_DISTANCE_THRESHOLD_CM + 5,
            elapsedSeconds: STABILITY_LOCK_DURATION_S + 1,
            piMode: false,
            piAttentionOk: true,
        });
        expect(result).toBe("reset_drift");
    });
});
