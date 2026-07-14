"use client";

import { useEffect, useState, useRef } from "react";
import { motion } from "framer-motion";
import { useAppStore } from "@/lib/store";
import { ACUITY_LEVELS } from "@/lib/constants";

export default function ResultsScreen() {
    const testResult = useAppStore((s) => s.testResult);
    const setScreen = useAppStore((s) => s.setScreen);
    const resetTest = useAppStore((s) => s.resetTest);
    const resultsRef = useRef<HTMLDivElement>(null);

    const [animatedLogMAR, setAnimatedLogMAR] = useState(1.0);
    const [showConfetti, setShowConfetti] = useState(false);

    useEffect(() => {
        if (!testResult) return;

        // Animate LogMAR counter
        const target = testResult.fractionalLogMAR;
        const duration = 1500;
        const start = Date.now();
        const startVal = 1.0;

        const tick = () => {
            const elapsed = Date.now() - start;
            const progress = Math.min(1, elapsed / duration);
            const eased = 1 - Math.pow(1 - progress, 3);
            setAnimatedLogMAR(startVal + (target - startVal) * eased);
            if (progress < 1) requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);

        if (target <= 0) setTimeout(() => setShowConfetti(true), 1800);
    }, [testResult]);

    if (!testResult) {
        return (
            <div className="flex min-h-screen items-center justify-center">
                <p className="text-text-secondary">No test results available.</p>
            </div>
        );
    }

    const durationMin = Math.floor(testResult.testDuration / 60000);
    const durationSec = Math.floor((testResult.testDuration % 60000) / 1000);

    // 4m-equivalent distance correction note
    const stdDistM = 4.0;
    const distCorrApplied = Math.abs(testResult.testDistance - stdDistM) > 0.05;
    const distCorrLogMAR = Math.log10(stdDistM) - Math.log10(Math.max(testResult.testDistance, 0.1));

    // Ambient light label
    // In Pi hardware mode the browser has no local camera, so the canvas
    // sampling returns 0 — display "Not measured" rather than "Low".
    const ambientLabel =
        testResult.ambientLightEstimate === 0 ? "Not measured" :
            testResult.ambientLightEstimate < 60 ? "Low" :
                testResult.ambientLightEstimate < 160 ? "Adequate" : "Bright";

    // Correction status label
    const correctionLabel =
        testResult.correctionStatus === "unaided" ? "Unaided (PVA)" :
            testResult.correctionStatus === "glasses" ? "With glasses" :
                "With contacts";

    // Eye label
    const eyeLabel =
        testResult.eyeTested === "OD" ? "Right eye (OD)" :
            testResult.eyeTested === "OS" ? "Left eye (OS)" : "Both eyes (OU)";

    // WHO classification colour
    const whoColor =
        testResult.fractionalLogMAR < 0.3 ? "text-success border-success/30 bg-success/10" :
            testResult.fractionalLogMAR < 0.5 ? "text-warning border-warning/30 bg-warning/10" :
                "text-danger  border-danger/30  bg-danger/10";

    const handleTestAgain = () => {
        resetTest();
        setScreen("camera-setup");
    };

    const handleDownloadPDF = async () => {
        try {
            const { default: jsPDF } = await import("jspdf");
            const doc = new jsPDF();
            const lineH = 8;
            let y = 20;

            const ln = (text: string, size = 11, color: [number, number, number] = [30, 30, 30]) => {
                doc.setFontSize(size);
                doc.setTextColor(...color);
                doc.text(text, 20, y);
                y += lineH;
            };

            const rule = () => {
                doc.setDrawColor(200, 200, 200);
                doc.line(20, y, 190, y);
                y += 4;
            };

            // Header
            doc.setFontSize(18);
            doc.setTextColor(0, 130, 100);
            doc.text("NadiVision \u2014 Clinical Visual Acuity Report", 20, y); y += 10;
            rule();

            // Patient / session info
            ln("Date:              " + new Date(testResult.date).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }));
            ln("Eye Tested:        " + eyeLabel);
            ln("Correction Status: " + correctionLabel);
            if (testResult.patientInfo?.age) ln("Age:               " + testResult.patientInfo.age);
            if (testResult.patientInfo?.gender) ln("Gender:            " + testResult.patientInfo.gender);
            ln("Test Duration:     " + durationMin + "m " + durationSec + "s");
            ln("Test Distance:     " + testResult.testDistance.toFixed(2) + " m");
            rule();

            // Primary results
            doc.setFontSize(16);
            doc.setTextColor(0, 0, 0);
            doc.text("Visual Acuity Results", 20, y); y += 10;

            ln("Snellen Acuity:    " + testResult.acuitySnellen, 12);
            ln("Decimal VA:        " + testResult.decimalVA.toFixed(2), 12);
            ln("LogMAR (fract.):   " + testResult.fractionalLogMAR.toFixed(2) + "  (95% CI: " + testResult.confidenceInterval.lower.toFixed(2) + " \u2013 " + testResult.confidenceInterval.upper.toFixed(2) + " LogMAR, \u00b11 line)", 12);
            ln("ETDRS Letter Score:" + " " + testResult.etdrsLetterScore + " / 70", 12);
            ln("WHO Classification:" + " " + testResult.whoClassification, 12);
            rule();

            // 4m-equivalent note
            if (distCorrApplied) {
                doc.setFontSize(10);
                doc.setTextColor(80, 80, 80);
                doc.text("4m-Equivalent Note: Optotype auto-scaled from actual test distance of " + testResult.testDistance.toFixed(2) + " m.", 20, y); y += 6;
                doc.text("  LogMAR correction applied: " + (distCorrLogMAR >= 0 ? "+" : "") + distCorrLogMAR.toFixed(3) + ". Reported score is 4m-equivalent.", 20, y); y += 10;
            }

            // Per-line breakdown
            doc.setFontSize(13);
            doc.setTextColor(0, 0, 0);
            doc.text("Per-Line Breakdown (ETDRS)", 20, y); y += 8;
            doc.setFontSize(10);
            for (const score of testResult.perLevelScores) {
                const pct = score.total > 0 ? Math.round((score.correct / score.total) * 100) : 0;
                const mark = score.level.snellen === testResult.acuitySnellen ? " \u2190 Best line" : "";
                doc.setTextColor(score.level.snellen === testResult.acuitySnellen ? 0 : 60, score.level.snellen === testResult.acuitySnellen ? 160 : 60, score.level.snellen === testResult.acuitySnellen ? 120 : 60);
                doc.text("  " + score.level.snellen.padEnd(8) + "  " + score.correct + "/" + score.total + " correct  (" + pct + "%)" + mark, 20, y);
                y += 6;
            }
            rule();

            // Ambient light
            doc.setFontSize(10);
            doc.setTextColor(120, 120, 120);
            doc.text("Ambient Light (camera estimate): " + ambientLabel + " (lum \u2248 " + testResult.ambientLightEstimate + "/255)", 20, y); y += 6;
            doc.text("Note: Clinical standard requires 80\u2013320 cd/m\u00b2 chart illumination.", 20, y); y += 10;

            // Footer
            doc.setFontSize(8);
            doc.setTextColor(160, 160, 160);
            doc.text("Generated by NadiVision \u2014 Camera-based ETDRS-style visual acuity testing", 20, 285);
            doc.text("Results are indicative. For clinical diagnosis, consult a qualified ophthalmologist.", 20, 290);

            doc.save("NadiVision_Report_" + new Date().toISOString().split("T")[0] + ".pdf");
        } catch (err) {
            console.error("PDF generation failed:", err);
        }
    };

    return (
        <div className="flex min-h-screen flex-col items-center justify-center px-6 py-12">
            {showConfetti && <ConfettiEffect />}

            <motion.div
                ref={resultsRef}
                className="max-w-lg w-full flex flex-col items-center"
                initial={{ opacity: 0, y: 30 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.6 }}
            >
                {/* Header */}
                <motion.div
                    className="text-center mb-8"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ delay: 0.3 }}
                >
                    <motion.div
                        className="text-4xl mb-2"
                        initial={{ scale: 0 }}
                        animate={{ scale: 1 }}
                        transition={{ delay: 0.5, type: "spring", stiffness: 200 }}
                    >
                        ✦
                    </motion.div>
                    <h2 className="text-3xl font-bold mb-1">Test Complete</h2>
                    <p className="text-text-secondary text-sm">
                        {eyeLabel} · {correctionLabel}
                    </p>
                </motion.div>

                {/* Main result card */}
                <motion.div
                    className="glass rounded-3xl p-8 w-full mb-6"
                    initial={{ opacity: 0, scale: 0.95 }}
                    animate={{ opacity: 1, scale: 1 }}
                    transition={{ delay: 0.5, duration: 0.5 }}
                >
                    {/* Snellen + WHO badge */}
                    <div className="text-center mb-5">
                        <p className="text-xs text-text-muted mb-1 uppercase tracking-wide">Visual Acuity</p>
                        <motion.p
                            className="text-6xl font-bold text-primary"
                            initial={{ opacity: 0 }}
                            animate={{ opacity: 1 }}
                            transition={{ delay: 0.8 }}
                        >
                            {testResult.acuitySnellen}
                        </motion.p>
                        <motion.div
                            className="mt-2 inline-flex"
                            initial={{ opacity: 0, scale: 0.9 }}
                            animate={{ opacity: 1, scale: 1 }}
                            transition={{ delay: 1.0 }}
                        >
                            <span className={`px-3 py-1 rounded-full text-xs font-semibold tracking-wide border ${whoColor}`}>
                                {testResult.whoClassification}
                            </span>
                        </motion.div>
                    </div>

                    {/* Metric grid */}
                    <div className="grid grid-cols-3 gap-3 mb-5">
                        <div className="bg-surface rounded-xl p-3 text-center">
                            <p className="text-xs text-text-muted mb-1">LogMAR</p>
                            <p className="text-lg font-mono font-semibold text-text-primary">
                                {animatedLogMAR.toFixed(2)}
                            </p>
                        </div>
                        <div className="bg-surface rounded-xl p-3 text-center">
                            <p className="text-xs text-text-muted mb-1">Decimal VA</p>
                            <p className="text-lg font-mono font-semibold text-text-primary">
                                {testResult.decimalVA.toFixed(2)}
                            </p>
                        </div>
                        <div className="bg-surface rounded-xl p-3 text-center">
                            <p className="text-xs text-text-muted mb-1">ETDRS</p>
                            <p className="text-lg font-mono font-semibold text-text-primary">
                                {testResult.etdrsLetterScore}<span className="text-xs text-text-muted">/70</span>
                            </p>
                        </div>
                    </div>

                    {/* 95% CI */}
                    <p className="text-xs text-text-muted text-center mb-5">
                        95% CI: {testResult.confidenceInterval.lower.toFixed(2)} – {testResult.confidenceInterval.upper.toFixed(2)} LogMAR &nbsp;·&nbsp; ±1 line (ETDRS repeatability)
                    </p>

                    {/* 4m-equivalent note */}
                    {distCorrApplied && (
                        <div className="bg-primary/5 border border-primary/20 rounded-xl p-3 mb-5 text-xs text-text-secondary leading-relaxed">
                            <span className="text-primary font-semibold">4m-equivalent score</span> — optotype auto-scaled
                            from actual test distance of {testResult.testDistance.toFixed(2)} m using angular subtension
                            formula (correction: {distCorrLogMAR >= 0 ? "+" : ""}{distCorrLogMAR.toFixed(3)} LogMAR applied).
                        </div>
                    )}

                    {/* Session meta */}
                    <div className="flex flex-wrap justify-center gap-x-6 gap-y-2 text-xs text-text-secondary">
                        <div className="text-center">
                            <p className="text-text-muted">Distance</p>
                            <p className="font-mono">{testResult.testDistance.toFixed(2)} m</p>
                        </div>
                        <div className="text-center">
                            <p className="text-text-muted">Duration</p>
                            <p className="font-mono">{durationMin}m {durationSec}s</p>
                        </div>
                        <div className="text-center">
                            <p className="text-text-muted">Trials</p>
                            <p className="font-mono">{testResult.responses.length}</p>
                        </div>
                        <div className="text-center">
                            <p className="text-text-muted">Ambient</p>
                            <p className="font-mono">{ambientLabel}</p>
                        </div>
                    </div>
                </motion.div>

                {/* Patient info card (if present) */}
                {testResult.patientInfo && (testResult.patientInfo.age || testResult.patientInfo.gender) && (
                    <motion.div
                        className="glass rounded-2xl px-6 py-4 w-full mb-6 flex gap-6 text-xs text-text-secondary"
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: 0.9 }}
                    >
                        {testResult.patientInfo.age && (
                            <div><p className="text-text-muted">Age</p><p className="font-mono">{testResult.patientInfo.age}</p></div>
                        )}
                        {testResult.patientInfo.gender && (
                            <div><p className="text-text-muted">Gender</p><p className="font-mono">{testResult.patientInfo.gender}</p></div>
                        )}
                        <div><p className="text-text-muted">Eye</p><p className="font-mono">{eyeLabel}</p></div>
                        <div><p className="text-text-muted">Correction</p><p className="font-mono">{correctionLabel}</p></div>
                    </motion.div>
                )}

                {/* Per-line breakdown */}
                <motion.div
                    className="glass rounded-2xl p-6 w-full mb-6"
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 1.0 }}
                >
                    <h3 className="text-sm font-medium text-text-muted mb-4 uppercase tracking-wide">
                        Per-line breakdown (ETDRS)
                    </h3>
                    <div className="space-y-3">
                        {testResult.perLevelScores.map((score, i) => {
                            const pct = score.total > 0 ? (score.correct / score.total) * 100 : 0;
                            const isBestLine = score.level.snellen === testResult.acuitySnellen;
                            return (
                                <motion.div
                                    key={score.level.snellen}
                                    className="flex items-center gap-3"
                                    initial={{ opacity: 0, x: -20 }}
                                    animate={{ opacity: 1, x: 0 }}
                                    transition={{ delay: 1.2 + i * 0.05 }}
                                >
                                    <span className={`text-sm font-mono w-16 ${isBestLine ? "text-primary font-bold" : "text-text-secondary"}`}>
                                        {score.level.snellen}
                                    </span>
                                    <div className="flex-1 h-4 bg-surface-light rounded-full overflow-hidden">
                                        <motion.div
                                            className={`h-full rounded-full ${pct >= 60 ? "bg-success" : pct >= 40 ? "bg-warning" : "bg-danger"}`}
                                            initial={{ width: 0 }}
                                            animate={{ width: `${pct}%` }}
                                            transition={{ delay: 1.4 + i * 0.05, duration: 0.6, ease: "easeOut" }}
                                        />
                                    </div>
                                    <span className="text-sm font-mono text-text-muted w-12 text-right">
                                        {score.correct}/{score.total}
                                    </span>
                                    {isBestLine && <span className="text-xs text-primary">←</span>}
                                </motion.div>
                            );
                        })}
                    </div>
                </motion.div>

                {/* Test integrity alerts */}
                {(testResult.cheatingFlags?.length ?? 0) > 0 && (
                    <motion.div
                        className="glass rounded-2xl p-5 w-full mb-6 border border-warning/20"
                        initial={{ opacity: 0, y: 20 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: 1.3 }}
                    >
                        <h3 className="text-sm font-medium text-warning mb-3 uppercase tracking-wide flex items-center gap-2">
                            <span>⚠</span> Test Integrity Alerts
                        </h3>
                        <div className="space-y-1.5">
                            {testResult.cheatingFlags.map((flag, i) => {
                                const labels: Record<string, string> = {
                                    fullscreen_exit: "Exited fullscreen",
                                    tab_switch: "Switched away from tab",
                                    face_lost: "Face left camera view",
                                    multiple_faces: "Multiple faces detected",
                                    fast_answer: "Unusually fast response",
                                    distance_jump: "Sudden distance change",
                                };
                                return (
                                    <div key={i} className="flex items-center justify-between text-xs">
                                        <span className="text-warning/80">{labels[flag.type] ?? flag.type}</span>
                                        <span className="text-text-muted font-mono">
                                            {flag.detail ? `${flag.detail} · ` : ""}{new Date(flag.timestamp).toLocaleTimeString()}
                                        </span>
                                    </div>
                                );
                            })}
                        </div>
                    </motion.div>
                )}

                {/* Action buttons */}
                <motion.div
                    className="flex gap-4"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ delay: 1.8 }}
                >
                    <motion.button
                        onClick={handleDownloadPDF}
                        className="px-6 py-3 rounded-xl border border-white/10 text-text-secondary font-medium hover:bg-surface-light transition-colors duration-200 cursor-pointer"
                        whileHover={{ y: -2 }}
                        whileTap={{ scale: 0.97 }}
                    >
                        Download PDF ↓
                    </motion.button>
                    <motion.button
                        onClick={handleTestAgain}
                        className="px-8 py-3 rounded-xl bg-primary text-background font-semibold glow-primary glow-primary-hover transition-all duration-300 cursor-pointer"
                        whileHover={{ y: -2 }}
                        whileTap={{ scale: 0.97 }}
                    >
                        Test Again ↻
                    </motion.button>
                </motion.div>
            </motion.div>
        </div>
    );
}

function ConfettiEffect() {
    const canvasRef = useRef<HTMLCanvasElement>(null);

    useEffect(() => {
        const canvas = canvasRef.current;
        if (!canvas) return;

        const ctx = canvas.getContext("2d");
        if (!ctx) return;

        canvas.width = window.innerWidth;
        canvas.height = window.innerHeight;

        const colors = ["#00D4AA", "#6366F1", "#F59E0B", "#10B981", "#EF4444"];
        const particles: {
            x: number;
            y: number;
            vx: number;
            vy: number;
            size: number;
            color: string;
            rotation: number;
            rotSpeed: number;
            opacity: number;
        }[] = [];

        for (let i = 0; i < 80; i++) {
            particles.push({
                x: canvas.width / 2 + (Math.random() - 0.5) * 200,
                y: canvas.height / 2,
                vx: (Math.random() - 0.5) * 8,
                vy: -Math.random() * 12 - 4,
                size: Math.random() * 8 + 3,
                color: colors[Math.floor(Math.random() * colors.length)],
                rotation: Math.random() * 360,
                rotSpeed: (Math.random() - 0.5) * 10,
                opacity: 1,
            });
        }

        let frame = 0;
        const maxFrames = 120;

        const animate = () => {
            if (frame >= maxFrames) return;

            ctx.clearRect(0, 0, canvas.width, canvas.height);

            for (const p of particles) {
                p.x += p.vx;
                p.vy += 0.2; // gravity
                p.y += p.vy;
                p.rotation += p.rotSpeed;
                p.opacity = Math.max(0, 1 - frame / maxFrames);

                ctx.save();
                ctx.translate(p.x, p.y);
                ctx.rotate((p.rotation * Math.PI) / 180);
                ctx.globalAlpha = p.opacity;
                ctx.fillStyle = p.color;
                ctx.fillRect(-p.size / 2, -p.size / 2, p.size, p.size * 0.6);
                ctx.restore();
            }

            frame++;
            requestAnimationFrame(animate);
        };

        animate();
    }, []);

    return (
        <canvas
            ref={canvasRef}
            className="fixed inset-0 pointer-events-none z-50"
        />
    );
}
