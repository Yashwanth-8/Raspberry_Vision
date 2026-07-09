"use client";

import { motion } from "framer-motion";
import { useAppStore } from "@/lib/store";
import { autoDetectScreenCalibration } from "@/lib/screen-calibration";
import type { CalibrationData } from "@/lib/types";

const EyeIcon = () => (
    <motion.svg
        width="160"
        height="160"
        viewBox="0 0 160 160"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className="drop-shadow-2xl"
    >
        {/* Outer eye shape */}
        <motion.path
            d="M20 80C20 80 50 30 80 30C110 30 140 80 140 80C140 80 110 130 80 130C50 130 20 80 20 80Z"
            stroke="#00D4AA"
            strokeWidth="3"
            fill="none"
            initial={{ pathLength: 0 }}
            animate={{ pathLength: 1 }}
            transition={{ duration: 1.5, ease: "easeInOut" }}
        />
        {/* Iris */}
        <motion.circle
            cx="80"
            cy="80"
            r="28"
            stroke="#00D4AA"
            strokeWidth="2.5"
            fill="none"
            initial={{ scale: 0, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ delay: 0.8, duration: 0.6, ease: "easeOut" }}
        />
        {/* Pupil */}
        <motion.circle
            cx="80"
            cy="80"
            r="14"
            fill="#00D4AA"
            initial={{ scale: 0 }}
            animate={{ scale: [0, 1.2, 0.9, 1] }}
            transition={{ delay: 1.2, duration: 0.8, ease: "easeOut" }}
        />
        {/* Light reflection */}
        <motion.circle
            cx="72"
            cy="72"
            r="5"
            fill="#0A0F1E"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 1.8, duration: 0.3 }}
        />
        {/* Scanning line */}
        <motion.line
            x1="30"
            y1="80"
            x2="130"
            y2="80"
            stroke="#00D4AA"
            strokeWidth="1"
            strokeDasharray="4 4"
            initial={{ opacity: 0 }}
            animate={{ opacity: [0, 0.5, 0] }}
            transition={{ delay: 2, duration: 2, repeat: Infinity, repeatDelay: 3 }}
        />
    </motion.svg>
);

const features = [
    {
        icon: "📸",
        title: "Camera-Powered",
        desc: "Uses your device camera to measure exact distance — no extra hardware needed",
    },
    {
        icon: "🎯",
        title: "Pixel-Perfect",
        desc: "Optotype sized to exact arcminute specifications, caliper-verifiable",
    },
    {
        icon: "🔒",
        title: "Stability Guard",
        desc: "Auto-locks if you move or tilt — ensures clinically valid results",
    },
];

export default function LandingScreen() {
    const setScreen = useAppStore((s) => s.setScreen);
    const calibration = useAppStore((s) => s.calibration);
    const optotypeType = useAppStore((s) => s.optotypeType);

    const handleStart = () => {
        // Detect mobile (touch-primary device)
        const mobile = window.matchMedia("(pointer: coarse)").matches || window.innerWidth < 768;
        useAppStore.getState().setIsMobile(mobile);

        // Auto-detect screen calibration (PPI/mmPerPx)
        const detection = autoDetectScreenCalibration();
        const cal: CalibrationData = {
            mmPerPx: detection.mmPerPx,
            deviceLabel: `${navigator.userAgent.slice(0, 40)} | ${detection.detectedPPI} PPI (${detection.method})`,
            calibratedAt: Date.now(),
        };

        // Store calibration for future sessions
        useAppStore.getState().setCalibration(cal);
        localStorage.setItem("nadi-calibration", JSON.stringify(cal));

        // Skip calibration screen entirely — go straight to IPD
        setScreen("ipd");
    };

    return (
        <div className="flex min-h-screen flex-col items-center justify-center px-6">
            {/* Hero section */}
            <motion.div
                className="flex flex-col items-center text-center max-w-2xl"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.6 }}
            >
                {/* Logo / Eye animation */}
                <motion.div
                    className="mb-8"
                    initial={{ y: -20 }}
                    animate={{ y: 0 }}
                    transition={{ delay: 0.2, duration: 0.6 }}
                >
                    <EyeIcon />
                </motion.div>

                {/* Title */}
                <motion.h1
                    className="text-5xl font-bold tracking-tight mb-4 md:text-6xl"
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.4, duration: 0.6 }}
                >
                    <span className="text-primary">Nadi</span>
                    <span className="text-text-primary">Vision</span>
                </motion.h1>

                {/* Subtitle */}
                <motion.p
                    className="text-xl text-text-secondary mb-2 max-w-md"
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.6, duration: 0.6 }}
                >
                    Clinical-grade visual acuity testing
                </motion.p>
                <motion.p
                    className="text-base text-text-muted mb-10"
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.7, duration: 0.6 }}
                >
                    Powered by computer vision. No extra hardware needed.
                </motion.p>

                {/* Optotype selector */}
                <motion.div
                    className="flex gap-3 mb-6"
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.8, duration: 0.6 }}
                >
                    <button
                        onClick={() => useAppStore.getState().setOptotypeType("tumbling-e")}
                        className={`px-5 py-2.5 rounded-xl text-sm font-medium transition-all duration-200 cursor-pointer ${optotypeType === "tumbling-e"
                                ? "bg-primary/20 text-primary border border-primary/40"
                                : "bg-surface border border-white/10 text-text-secondary hover:border-white/20"
                            }`}
                    >
                        <span className="mr-1.5 font-bold">E</span>Tumbling E
                    </button>
                    <button
                        onClick={() => useAppStore.getState().setOptotypeType("landolt-c")}
                        className={`px-5 py-2.5 rounded-xl text-sm font-medium transition-all duration-200 cursor-pointer ${optotypeType === "landolt-c"
                                ? "bg-primary/20 text-primary border border-primary/40"
                                : "bg-surface border border-white/10 text-text-secondary hover:border-white/20"
                            }`}
                    >
                        <span className="mr-1.5 font-bold">C</span>Landolt C
                    </button>
                </motion.div>

                {/* CTA Button */}
                <motion.button
                    onClick={handleStart}
                    className="relative px-10 py-4 rounded-2xl bg-primary text-background font-semibold text-lg glow-primary glow-primary-hover transition-all duration-300 cursor-pointer hover:scale-[1.03] active:scale-[0.98]"
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.9, duration: 0.6 }}
                    whileHover={{ y: -2 }}
                    whileTap={{ scale: 0.97 }}
                >
                    <span className="relative z-10 flex items-center gap-2">
                        Begin Test
                        <motion.span
                            animate={{ x: [0, 4, 0] }}
                            transition={{ duration: 1.5, repeat: Infinity }}
                        >
                            →
                        </motion.span>
                    </span>
                </motion.button>
            </motion.div>

            {/* Features */}
            <motion.div
                className="mt-20 grid grid-cols-1 md:grid-cols-3 gap-6 max-w-3xl w-full px-4"
                initial={{ opacity: 0, y: 40 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 1.2, duration: 0.8 }}
            >
                {features.map((f, i) => (
                    <motion.div
                        key={f.title}
                        className="glass rounded-2xl p-6 text-center hover:border-primary/30 transition-colors duration-300"
                        initial={{ opacity: 0, y: 20 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: 1.4 + i * 0.15, duration: 0.5 }}
                        whileHover={{ y: -4, transition: { duration: 0.2 } }}
                    >
                        <div className="text-3xl mb-3">{f.icon}</div>
                        <h3 className="text-base font-semibold text-text-primary mb-1">
                            {f.title}
                        </h3>
                        <p className="text-sm text-text-secondary leading-relaxed">
                            {f.desc}
                        </p>
                    </motion.div>
                ))}
            </motion.div>

            {/* Bottom text */}
            <motion.p
                className="mt-12 mb-8 text-xs text-text-muted"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: 2, duration: 1 }}
            >
                Works on laptop &amp; phone · ESP32 BLE remote compatible
            </motion.p>
        </div>
    );
}
