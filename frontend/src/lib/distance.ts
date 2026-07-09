/**
 * Camera-based distance estimation using MediaPipe Face Mesh landmarks.
 *
 * Uses the pinhole camera model:  d = f_px × D_real / P_measured
 *
 * Three references with confidence weighting:
 *   1. Iris diameter (landmarks 468-472 left, 473-477 right) — best < 2.5m
 *   2. Interpupillary distance (landmark 468 & 473 centers) — best 1-4m
 *   3. Face bizygomatic width (landmarks 234 & 454) — best 3-6m
 */

import { IRIS_DIAMETER_MM, DEFAULT_IPD_MM, AVG_FACE_WIDTH_MM } from "./constants";

export interface FocalLengthCalibration {
    focalLengthPx: number;
    calibratedAt: number;
}

/**
 * Estimate focal length in pixels from a known reference at a known distance.
 * f_px = P_measured × d / D_real
 */
export function calibrateFocalLength(
    pixelSize: number,
    knownDistanceM: number,
    realSizeMm: number
): number {
    return (pixelSize * knownDistanceM) / (realSizeMm / 1000);
}

/**
 * Auto-estimate focal length from camera stream track settings.
 * Uses getSettings() for FOV when available, otherwise falls back to typical webcam FOV.
 *
 * f_px = (imageWidth / 2) / tan(hFOV_rad / 2)
 */
export function autoEstimateFocalLength(
    stream: MediaStream,
    imageWidth: number
): number {
    const track = stream.getVideoTracks()[0];
    if (!track) return defaultFocalLength(imageWidth);

    const settings = track.getSettings() as any;

    // Some browsers/cameras expose focalLength (physical mm) and sensor dimensions
    // Chrome may also expose zoom / field-of-view related capabilities
    if (settings.focalLength && settings.focalLength > 0) {
        // Physical focal length in mm. Estimate sensor width from common sensors.
        // Most webcam sensors are ~3.6-6mm wide. Use 4.8mm as reasonable default.
        const sensorWidthMm = 4.8;
        return (settings.focalLength / sensorWidthMm) * imageWidth;
    }

    // Fallback: typical webcam horizontal FOV is ~55-65 degrees
    // Use 60° as a solid default (works for most laptop webcams)
    return defaultFocalLength(imageWidth);
}

/**
 * Default focal length estimate using typical 60° horizontal FOV.
 */
export function defaultFocalLength(imageWidth: number): number {
    const hFovDeg = 60;
    const hFovRad = (hFovDeg * Math.PI) / 180;
    return (imageWidth / 2) / Math.tan(hFovRad / 2);
}

/**
 * Euclidean distance between two 2D points.
 */
function dist2d(a: { x: number; y: number }, b: { x: number; y: number }): number {
    return Math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2);
}

export interface LandmarkPoint {
    x: number; // 0-1 normalized
    y: number;
    z: number;
}

export interface DistanceEstimate {
    distance: number; // meters
    confidence: number; // 0-1
    method: "iris" | "ipd" | "face_width";
}

/**
 * Estimate distance from iris landmarks.
 */
export function estimateFromIris(
    landmarks: LandmarkPoint[],
    focalLengthPx: number,
    imageWidth: number,
    imageHeight: number
): DistanceEstimate | null {
    // MediaPipe Face Mesh iris landmarks:
    // Left iris: 468 (center), 469-472 (boundary)
    // Right iris: 473 (center), 474-477 (boundary)
    if (landmarks.length < 478) return null;

    const leftIrisCenter = landmarks[468];
    const rightIrisCenter = landmarks[473];

    // Left iris horizontal diameter: landmarks 469 (left) and 471 (right)
    const li469 = landmarks[469];
    const li471 = landmarks[471];
    const leftDiamPx = dist2d(
        { x: li469.x * imageWidth, y: li469.y * imageHeight },
        { x: li471.x * imageWidth, y: li471.y * imageHeight }
    );

    // Right iris horizontal diameter: landmarks 474 (left) and 476 (right)
    const ri474 = landmarks[474];
    const ri476 = landmarks[476];
    const rightDiamPx = dist2d(
        { x: ri474.x * imageWidth, y: ri474.y * imageHeight },
        { x: ri476.x * imageWidth, y: ri476.y * imageHeight }
    );

    const avgIrisPx = (leftDiamPx + rightDiamPx) / 2;
    if (avgIrisPx < 3) return null; // too few pixels

    const distanceM = (focalLengthPx * (IRIS_DIAMETER_MM / 1000)) / avgIrisPx;
    const confidence = Math.min(1, avgIrisPx / 20); // more pixels = more confident

    return { distance: distanceM, confidence, method: "iris" };
}

/**
 * Estimate distance from IPD.
 */
export function estimateFromIPD(
    landmarks: LandmarkPoint[],
    focalLengthPx: number,
    ipdMm: number,
    imageWidth: number,
    imageHeight: number
): DistanceEstimate | null {
    if (landmarks.length < 478) return null;

    const leftIrisCenter = landmarks[468];
    const rightIrisCenter = landmarks[473];

    const ipdPx = dist2d(
        { x: leftIrisCenter.x * imageWidth, y: leftIrisCenter.y * imageHeight },
        { x: rightIrisCenter.x * imageWidth, y: rightIrisCenter.y * imageHeight }
    );

    if (ipdPx < 10) return null;

    const distanceM = (focalLengthPx * (ipdMm / 1000)) / ipdPx;
    const confidence = Math.min(1, ipdPx / 50);

    return { distance: distanceM, confidence, method: "ipd" };
}

/**
 * Estimate distance from face width (bizygomatic).
 */
export function estimateFromFaceWidth(
    landmarks: LandmarkPoint[],
    focalLengthPx: number,
    imageWidth: number,
    imageHeight: number
): DistanceEstimate | null {
    if (landmarks.length < 455) return null;

    const left = landmarks[234];
    const right = landmarks[454];

    const faceWidthPx = dist2d(
        { x: left.x * imageWidth, y: left.y * imageHeight },
        { x: right.x * imageWidth, y: right.y * imageHeight }
    );

    if (faceWidthPx < 20) return null;

    const distanceM = (focalLengthPx * (AVG_FACE_WIDTH_MM / 1000)) / faceWidthPx;
    const confidence = Math.min(1, faceWidthPx / 100) * 0.7; // lower max confidence for face width

    return { distance: distanceM, confidence, method: "face_width" };
}

/**
 * Fuse multiple distance estimates using confidence-weighted average.
 */
export function fuseDistanceEstimates(estimates: DistanceEstimate[]): {
    distance: number;
    confidence: number;
} {
    const valid = estimates.filter((e) => e.distance > 0.1 && e.distance < 10);
    if (valid.length === 0) return { distance: 0, confidence: 0 };

    let totalWeight = 0;
    let weightedSum = 0;

    for (const est of valid) {
        weightedSum += est.distance * est.confidence;
        totalWeight += est.confidence;
    }

    return {
        distance: weightedSum / totalWeight,
        confidence: Math.min(1, totalWeight / valid.length),
    };
}
