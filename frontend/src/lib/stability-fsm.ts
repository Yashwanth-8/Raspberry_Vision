/**
 * stability-fsm.ts
 *
 * Pure function for the STABILIZING → outcome step of the distance-stability FSM.
 * Extracted from TestScreen.tsx so it can be unit-tested independently.
 *
 * Deliverable 1.X — Attention-Stability Gate Coupling.
 */

import { STABILITY_LOCK_DURATION_S, STABILITY_DISTANCE_THRESHOLD_CM } from "./constants";

/** All possible outcomes of one stability-FSM tick while in STABILIZING state. */
export type StabilizingOutcome =
    | "reset_attention"   // piAttentionOk=false during countdown → reset to LOCKED
    | "reset_drift"       // distance drifted beyond threshold during countdown → reset to LOCKED
    | "counting"          // countdown still in progress
    | "unlocked";         // countdown complete → transition to UNLOCKED

export interface StabilizingInputs {
    distDriftCm: number;       // |currentDist - anchor| in centimetres
    elapsedSeconds: number;    // seconds since countdown started
    piMode: boolean;           // true when connected to Pi backend
    piAttentionOk: boolean;    // current attention signal from backend
}

/**
 * Compute the outcome for a single tick of the stability FSM while in
 * STABILIZING (countdown) state.
 *
 * Priority order:
 *   1. Attention lost (piMode + !piAttentionOk)  → reset_attention
 *   2. Distance drifted > threshold              → reset_drift
 *   3. Countdown complete                        → unlocked
 *   4. Default                                   → counting
 */
export function stepStabilizing(inputs: StabilizingInputs): StabilizingOutcome {
    const { distDriftCm, elapsedSeconds, piMode, piAttentionOk } = inputs;

    if (piMode && !piAttentionOk) {
        return "reset_attention";
    }

    if (distDriftCm > STABILITY_DISTANCE_THRESHOLD_CM) {
        return "reset_drift";
    }

    if (elapsedSeconds >= STABILITY_LOCK_DURATION_S) {
        return "unlocked";
    }

    return "counting";
}
