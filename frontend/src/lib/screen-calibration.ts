/**
 * Auto-detect screen calibration (mmPerPx) for accurate optotype rendering.
 * 
 * Uses multiple strategies:
 * 1. CSS resolution media queries (most accurate when available)
 * 2. devicePixelRatio + empirical device class defaults
 * 3. Fallback to standard CSS 96 PPI
 */

export interface ScreenCalibrationResult {
    mmPerPx: number;
    detectedPPI: number;
    method: 'css-resolution' | 'device-pixel-ratio' | 'fallback';
    confidence: 'high' | 'medium' | 'low';
}

/**
 * Detects physical screen PPI using CSS resolution media queries.
 * Returns null if not supported or detection fails.
 */
function detectPPIFromCSS(): number | null {
    // Try common DPI values
    const testValues = [96, 110, 120, 140, 150, 160, 192, 220, 264, 326, 401, 458];

    for (const dpi of testValues) {
        if (window.matchMedia(`(resolution: ${dpi}dpi)`).matches) {
            return dpi;
        }
    }

    // Try with tolerances (some browsers report slightly different values)
    for (const dpi of testValues) {
        const lower = dpi - 2;
        const upper = dpi + 2;
        if (window.matchMedia(`(min-resolution: ${lower}dpi) and (max-resolution: ${upper}dpi)`).matches) {
            return dpi;
        }
    }

    return null;
}

/**
 * Auto-detect screen calibration.
 * Call this on app start to skip manual credit card calibration.
 */
export function autoDetectScreenCalibration(): ScreenCalibrationResult {
    // Strategy 1: CSS resolution media queries (best accuracy)
    const cssPPI = detectPPIFromCSS();
    if (cssPPI) {
        return {
            mmPerPx: 25.4 / cssPPI,
            detectedPPI: cssPPI,
            method: 'css-resolution',
            confidence: 'high',
        };
    }

    // Strategy 2: devicePixelRatio + device class heuristics
    const dpr = window.devicePixelRatio || 1;
    const screenWidth = window.screen.width;
    const screenHeight = window.screen.height;
    const isMobile = window.matchMedia("(pointer: coarse)").matches || screenWidth < 768;

    let estimatedPPI: number;
    let confidence: 'medium' | 'low';

    if (isMobile) {
        // Mobile devices typically high-DPI: 350-450 physical PPI
        // Empirical: iPhone ~326-460 PPI, Android flagship ~400-550 PPI
        // Safe conservative estimate
        estimatedPPI = 140; // Effective PPI after devicePixelRatio scaling
        confidence = 'medium';
    } else if (dpr >= 2) {
        // HiDPI/Retina displays (MacBook Pro, Dell XPS, etc.)
        // Typically 220 physical PPI → ~110 CSS PPI at 2x scaling
        estimatedPPI = 110;
        confidence = 'medium';
    } else if (dpr > 1 && dpr < 2) {
        // 1.25x, 1.5x scaling (Windows laptops)
        estimatedPPI = 96 * dpr;
        confidence = 'medium';
    } else {
        // Standard desktop monitor: 96 PPI (CSS standard)
        estimatedPPI = 96;
        confidence = 'low';
    }

    return {
        mmPerPx: 25.4 / estimatedPPI,
        detectedPPI: estimatedPPI,
        method: 'device-pixel-ratio',
        confidence,
    };
}

/**
 * Get user-friendly description of detection method
 */
export function getCalibrationDescription(result: ScreenCalibrationResult): string {
    switch (result.method) {
        case 'css-resolution':
            return `Auto-detected: ${result.detectedPPI} PPI (high confidence)`;
        case 'device-pixel-ratio':
            return `Estimated: ~${result.detectedPPI} PPI (${result.confidence} confidence)`;
        case 'fallback':
            return `Default: ${result.detectedPPI} PPI (standard desktop)`;
    }
}
