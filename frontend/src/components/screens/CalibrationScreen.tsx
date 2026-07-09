"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { motion } from "framer-motion";
import { useAppStore } from "@/lib/store";
import type { CalibrationData } from "@/lib/types";

// Credit card standard: 85.6mm × 53.98mm
const CARD_WIDTH_MM = 85.6;
const CARD_HEIGHT_MM = 53.98;

export default function CalibrationScreen() {
    const setScreen = useAppStore((s) => s.setScreen);
    const setCalibration = useAppStore((s) => s.setCalibration);

    // Slider-based width in px — user adjusts until the on-screen rectangle matches a real credit card
    const [widthPx, setWidthPx] = useState(320);
    const containerRef = useRef<HTMLDivElement>(null);

    const heightPx = (widthPx * CARD_HEIGHT_MM) / CARD_WIDTH_MM;
    const mmPerPx = CARD_WIDTH_MM / widthPx;

    const handleConfirm = () => {
        const cal: CalibrationData = {
            mmPerPx,
            deviceLabel: navigator.userAgent.slice(0, 60),
            calibratedAt: Date.now(),
        };
        setCalibration(cal);
        localStorage.setItem("nadi-calibration", JSON.stringify(cal));
        setScreen("ipd");
    };

    return (
        <div className="flex min-h-screen flex-col items-center justify-center px-6">
            {/* Progress bar */}
            <div className="fixed top-0 left-0 right-0 h-1 bg-surface z-50">
                <motion.div
                    className="h-full bg-primary"
                    initial={{ width: "0%" }}
                    animate={{ width: "33%" }}
                    transition={{ duration: 0.6 }}
                />
            </div>

            <motion.div
                className="max-w-lg w-full flex flex-col items-center text-center"
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5 }}
            >
                <p className="text-sm text-text-muted mb-2 font-medium tracking-wide uppercase">
                    Step 1 of 3
                </p>
                <h2 className="text-3xl font-bold mb-2">Screen Calibration</h2>
                <p className="text-text-secondary mb-8 max-w-sm">
                    Place a standard credit card on the rectangle below. Adjust the slider until it matches
                    exactly.
                </p>

                {/* Card rectangle */}
                <div
                    ref={containerRef}
                    className="relative mb-8 flex items-center justify-center"
                    style={{ minHeight: "200px" }}
                >
                    <motion.div
                        className="border-2 border-dashed border-primary/60 rounded-lg relative flex items-center justify-center"
                        style={{
                            width: `${widthPx}px`,
                            height: `${heightPx}px`,
                        }}
                        layout
                        transition={{ type: "spring", stiffness: 300, damping: 30 }}
                    >
                        {/* Corner markers */}
                        {[
                            "top-0 left-0 border-t-2 border-l-2 rounded-tl-lg",
                            "top-0 right-0 border-t-2 border-r-2 rounded-tr-lg",
                            "bottom-0 left-0 border-b-2 border-l-2 rounded-bl-lg",
                            "bottom-0 right-0 border-b-2 border-r-2 rounded-br-lg",
                        ].map((pos, i) => (
                            <div
                                key={i}
                                className={`absolute w-5 h-5 border-primary ${pos}`}
                            />
                        ))}

                        {/* Dimensions label */}
                        <div className="text-xs text-text-muted font-mono">
                            {CARD_WIDTH_MM} × {CARD_HEIGHT_MM} mm
                        </div>
                    </motion.div>
                </div>

                {/* Slider */}
                <div className="w-full max-w-sm mb-4">
                    <input
                        type="range"
                        min={200}
                        max={500}
                        step={1}
                        value={widthPx}
                        onChange={(e) => setWidthPx(Number(e.target.value))}
                        className="w-full h-2 rounded-full appearance-none cursor-pointer bg-surface-light accent-primary"
                    />
                </div>

                <p className="text-sm text-text-muted font-mono mb-8">
                    {mmPerPx.toFixed(4)} mm/px · {(1 / mmPerPx).toFixed(1)} px/mm
                </p>

                {/* Confirm button */}
                <motion.button
                    onClick={handleConfirm}
                    className="px-8 py-3 rounded-xl bg-primary text-background font-semibold glow-primary glow-primary-hover transition-all duration-300 cursor-pointer hover:scale-[1.02] active:scale-[0.98]"
                    whileHover={{ y: -2 }}
                    whileTap={{ scale: 0.97 }}
                >
                    Confirm Calibration ✓
                </motion.button>
            </motion.div>
        </div>
    );
}
