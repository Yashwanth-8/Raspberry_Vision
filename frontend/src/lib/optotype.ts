import { E_STROKES } from "./constants";
import type { EDirection } from "./types";

/**
 * Calculate the physical height (mm) of the Tumbling E for a given acuity level at a distance.
 *
 * E height  = d × tan(totalArcMin × π / (180 × 60))
 * totalArcMin = arcMinPerStroke × E_STROKES (5)
 */
export function optotypeHeightMm(
    distanceMeters: number,
    arcMinPerStroke: number
): number {
    const totalArcMin = arcMinPerStroke * E_STROKES;
    const radians = (totalArcMin * Math.PI) / (180 * 60);
    return distanceMeters * Math.tan(radians) * 1000; // convert m to mm
}

/**
 * Convert mm to CSS pixels using calibration data.
 */
export function mmToPx(mm: number, mmPerPx: number): number {
    return mm / mmPerPx;
}

/**
 * Compute optotype height in CSS pixels for screen rendering.
 */
export function optotypeHeightPx(
    distanceMeters: number,
    arcMinPerStroke: number,
    mmPerPx: number
): number {
    const heightMm = optotypeHeightMm(distanceMeters, arcMinPerStroke);
    return mmToPx(heightMm, mmPerPx);
}

/**
 * Pick a random direction.
 */
export function randomDirection(): EDirection {
    const dirs: EDirection[] = ["up", "down", "left", "right"];
    return dirs[Math.floor(Math.random() * dirs.length)];
}

/**
 * Pick a random direction, avoiding consecutive repeats for better test validity.
 */
export function smartRandomDirection(lastDirection?: EDirection): EDirection {
    const dirs: EDirection[] = ["up", "down", "left", "right"];
    const available = lastDirection ? dirs.filter(d => d !== lastDirection) : dirs;
    return available[Math.floor(Math.random() * available.length)];
}

/**
 * Rotation angle (degrees) for the Tumbling E based on its facing direction.
 * The base E faces RIGHT.
 */
export function directionToRotation(dir: EDirection): number {
    switch (dir) {
        case "right": return 0;
        case "down": return 90;
        case "left": return 180;
        case "up": return 270;
    }
}
