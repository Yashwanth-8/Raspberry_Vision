"use client";

import { motion } from "framer-motion";
import { useAppStore } from "@/lib/store";

export default function IPDScreen() {
    const setScreen = useAppStore((s) => s.setScreen);
    const ipd = useAppStore((s) => s.ipd);
    const setIpd = useAppStore((s) => s.setIpd);
    const isMobile = useAppStore((s) => s.isMobile);
    const nextScreen = isMobile ? "mobile-calibration" : "camera-setup";

    return (
        <div className="flex min-h-screen flex-col items-center justify-center px-6">
            {/* Progress bar */}
            <div className="fixed top-0 left-0 right-0 h-1 bg-surface z-50">
                <motion.div
                    className="h-full bg-primary"
                    initial={{ width: "33%" }}
                    animate={{ width: "66%" }}
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
                    Step 2 of 3
                </p>
                <h2 className="text-3xl font-bold mb-2">Interpupillary Distance</h2>
                <p className="text-text-secondary mb-10 max-w-sm">
                    For the most accurate distance measurement, enter your IPD. Most adults
                    are between 58–70mm.
                </p>

                {/* IPD visual */}
                <div className="relative mb-8 flex items-center justify-center">
                    <svg width="200" height="80" viewBox="0 0 200 80" fill="none">
                        {/* Left eye */}
                        <ellipse cx="60" cy="40" rx="22" ry="14" stroke="#00D4AA" strokeWidth="2" fill="none" />
                        <circle cx="60" cy="40" r="7" fill="#00D4AA" opacity="0.8" />
                        {/* Right eye */}
                        <ellipse cx="140" cy="40" rx="22" ry="14" stroke="#00D4AA" strokeWidth="2" fill="none" />
                        <circle cx="140" cy="40" r="7" fill="#00D4AA" opacity="0.8" />
                        {/* Distance line */}
                        <line x1="60" y1="65" x2="140" y2="65" stroke="#9CA3AF" strokeWidth="1" strokeDasharray="4 2" />
                        <line x1="60" y1="60" x2="60" y2="70" stroke="#9CA3AF" strokeWidth="1" />
                        <line x1="140" y1="60" x2="140" y2="70" stroke="#9CA3AF" strokeWidth="1" />
                    </svg>
                </div>

                {/* IPD value */}
                <div className="text-5xl font-bold font-mono text-primary mb-6">
                    {ipd}<span className="text-xl text-text-muted ml-1">mm</span>
                </div>

                {/* Slider */}
                <div className="w-full max-w-sm mb-8">
                    <input
                        type="range"
                        min={50}
                        max={80}
                        step={0.5}
                        value={ipd}
                        onChange={(e) => setIpd(Number(e.target.value))}
                        className="w-full h-2 rounded-full appearance-none cursor-pointer bg-surface-light accent-primary"
                    />
                    <div className="flex justify-between text-xs text-text-muted mt-2">
                        <span>50mm</span>
                        <span>80mm</span>
                    </div>
                </div>

                {/* Buttons */}
                <div className="flex gap-4">
                    <motion.button
                        onClick={() => {
                            setIpd(63);
                            setScreen(nextScreen);
                        }}
                        className="px-6 py-3 rounded-xl border border-white/10 text-text-secondary font-medium hover:bg-surface-light transition-colors duration-200 cursor-pointer"
                        whileHover={{ y: -2 }}
                        whileTap={{ scale: 0.97 }}
                    >
                        Skip — use default
                    </motion.button>
                    <motion.button
                        onClick={() => setScreen(nextScreen)}
                        className="px-8 py-3 rounded-xl bg-primary text-background font-semibold glow-primary glow-primary-hover transition-all duration-300 cursor-pointer hover:scale-[1.02] active:scale-[0.98]"
                        whileHover={{ y: -2 }}
                        whileTap={{ scale: 0.97 }}
                    >
                        Continue →
                    </motion.button>
                </div>
            </motion.div>
        </div>
    );
}
