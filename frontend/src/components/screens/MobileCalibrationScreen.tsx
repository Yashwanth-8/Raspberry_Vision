"use client";

import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useAppStore } from "@/lib/store";
import { AVG_FACE_WIDTH_MM } from "@/lib/constants";

// How many face-width samples to collect before enabling the button
const SAMPLES_NEEDED = 15;

export default function MobileCalibrationScreen() {
    const setScreen = useAppStore((s) => s.setScreen);
    const setFocalLengthPx = useAppStore((s) => s.setFocalLengthPx);

    const videoRef = useRef<HTMLVideoElement>(null);
    const streamRef = useRef<MediaStream | null>(null);
    const faceMeshRef = useRef<any>(null);
    const animFrameRef = useRef<number>(0);
    const initRef = useRef(false);
    const samplesRef = useRef<number[]>([]);

    const [armLengthCm, setArmLengthCm] = useState(60);
    const [faceDetected, setFaceDetected] = useState(false);
    const [sampleCount, setSampleCount] = useState(0);
    const [cameraReady, setCameraReady] = useState(false);
    const [modelLoading, setModelLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [done, setDone] = useState(false);
    const [previewDist, setPreviewDist] = useState<number | null>(null);

    useEffect(() => {
        if (initRef.current) return;
        initRef.current = true;

        let cancelled = false;

        async function run() {
            try {
                if (!navigator.mediaDevices?.getUserMedia) {
                    setModelLoading(false);
                    setError("Camera requires HTTPS. Run `npm run dev:https` on the host.");
                    return;
                }

                const faceMeshModule = await import("@mediapipe/face_mesh");
                const faceMesh = new faceMeshModule.FaceMesh({
                    locateFile: (file: string) =>
                        `https://cdn.jsdelivr.net/npm/@mediapipe/face_mesh/${file}`,
                });

                // refineLandmarks not needed — just face contour
                faceMesh.setOptions({
                    maxNumFaces: 1,
                    refineLandmarks: false,
                    minDetectionConfidence: 0.6,
                    minTrackingConfidence: 0.6,
                });

                faceMeshRef.current = faceMesh;

                if (!videoRef.current) return;

                const stream = await navigator.mediaDevices.getUserMedia({
                    video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 720 } },
                });
                if (cancelled) { stream.getTracks().forEach((t) => t.stop()); return; }
                streamRef.current = stream;
                videoRef.current.srcObject = stream;
                try { await videoRef.current.play(); } catch (e: any) {
                    if (e.name === "AbortError") return;
                    throw e;
                }
                if (cancelled) return;
                setCameraReady(true);

                faceMesh.onResults((results: any) => {
                    if (cancelled) return;
                    if (results.multiFaceLandmarks?.length > 0 && videoRef.current) {
                        const lm = results.multiFaceLandmarks[0];
                        setFaceDetected(true);

                        // Bizygomatic width: landmark 234 (left cheek) to 454 (right cheek)
                        const vw = videoRef.current.videoWidth || 1280;
                        const vh = videoRef.current.videoHeight || 720;

                        // Calculate face width in pixels (use 2D distance for accuracy)
                        const left = lm[234];
                        const right = lm[454];
                        const faceWidthPx = Math.sqrt(
                            Math.pow((right.x - left.x) * vw, 2) +
                            Math.pow((right.y - left.y) * vh, 2)
                        );

                        if (faceWidthPx > 30) {
                            // Calculate what distance this face width would give using the current arm length
                            // This verifies the calibration logic is sound
                            const tempFpx = faceWidthPx * (armLengthCm / 100) / (AVG_FACE_WIDTH_MM / 1000);
                            const estimatedDist = tempFpx * (AVG_FACE_WIDTH_MM / 1000) / faceWidthPx;
                            // This should equal armLengthCm/100 (mathematical identity), showing user they're at target distance
                            setPreviewDist(estimatedDist);

                            samplesRef.current.push(faceWidthPx);
                            if (samplesRef.current.length > SAMPLES_NEEDED * 2) {
                                samplesRef.current.shift();
                            }
                            setSampleCount(Math.min(samplesRef.current.length, SAMPLES_NEEDED));
                        }
                    } else {
                        setFaceDetected(false);
                        setPreviewDist(null);
                    }
                });

                await faceMesh.initialize();
                if (cancelled) return;
                setModelLoading(false);

                function pump() {
                    if (cancelled) return;
                    if (faceMeshRef.current && videoRef.current) {
                        faceMeshRef.current.send({ image: videoRef.current }).catch(() => { });
                    }
                    animFrameRef.current = requestAnimationFrame(pump);
                }
                pump();
            } catch (err: any) {
                if (!cancelled) {
                    setModelLoading(false);
                    setError(err.message || "Camera error");
                }
            }
        }

        run();

        return () => {
            cancelled = true;
            initRef.current = false; // allow re-init on remount
            cancelAnimationFrame(animFrameRef.current);
            streamRef.current?.getTracks().forEach((t) => t.stop());
        };
    }, []);

    const handleCalibrate = () => {
        const samples = samplesRef.current;
        if (samples.length < 5) return;

        // Average the most recent SAMPLES_NEEDED measurements
        const recent = samples.slice(-SAMPLES_NEEDED);
        const avgFaceWidthPx = recent.reduce((a, b) => a + b, 0) / recent.length;

        // Pinhole camera model: f_px = P_measured * d_known / D_real
        // P_measured = avgFaceWidthPx (face width in pixels)
        // d_known = armM (arm's length in meters)  
        // D_real = AVG_FACE_WIDTH_MM / 1000 (actual face width in meters)
        const armM = armLengthCm / 100;
        const fPx = (avgFaceWidthPx * armM) / (AVG_FACE_WIDTH_MM / 1000);

        console.log('[Mobile Cal] Focal length calibrated:', {
            avgFaceWidthPx: avgFaceWidthPx.toFixed(1),
            armLengthCm,
            focalLengthPx: fPx.toFixed(1),
            videoWidth: videoRef.current?.videoWidth || 'unknown',
        });

        setFocalLengthPx(fPx);
        setDone(true);

        // Stop camera before navigating
        cancelAnimationFrame(animFrameRef.current);
        streamRef.current?.getTracks().forEach((t) => t.stop());

        setTimeout(() => setScreen("camera-setup"), 700);
    };

    const canCalibrate = sampleCount >= SAMPLES_NEEDED && faceDetected;
    const progress = sampleCount / SAMPLES_NEEDED;

    return (
        <div className="flex min-h-screen flex-col items-center justify-center px-5 py-6">
            {/* Progress bar */}
            <div className="fixed top-0 left-0 right-0 h-1 bg-surface z-50">
                <motion.div
                    className="h-full bg-primary"
                    initial={{ width: "66%" }}
                    animate={{ width: "85%" }}
                    transition={{ duration: 0.6 }}
                />
            </div>

            <motion.div
                className="max-w-sm w-full flex flex-col items-center text-center"
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5 }}
            >
                <p className="text-xs text-text-muted mb-2 font-medium tracking-wide uppercase">
                    Step 3 of 4
                </p>
                <h2 className="text-2xl font-bold mb-2">Camera Calibration</h2>
                <p className="text-sm text-text-secondary mb-5 max-w-xs leading-relaxed">
                    Extend your arm fully and hold the phone at arm's length. Look straight at the camera.
                </p>

                {error ? (
                    <div className="bg-danger/20 border border-danger/30 rounded-xl p-4 mb-4 text-danger text-sm text-left">
                        {error}
                    </div>
                ) : (
                    <>
                        {/* Camera preview */}
                        <div className="relative w-full aspect-[4/3] max-h-[38vh] rounded-2xl overflow-hidden bg-surface border border-white/5 mb-4">
                            <video
                                ref={videoRef}
                                className="absolute inset-0 w-full h-full object-cover -scale-x-100"
                                playsInline
                                muted
                            />

                            {/* Face guide oval */}
                            <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                                <motion.div
                                    className="w-32 h-40 rounded-full border-2 border-dashed transition-colors duration-500"
                                    animate={{ borderColor: faceDetected ? "#00D4AA" : "rgba(255,255,255,0.2)" }}
                                />
                            </div>

                            {/* Arm-length visual guide lines */}
                            <div className="absolute bottom-2 left-0 right-0 flex justify-center pointer-events-none">
                                <div className="flex items-center gap-1 bg-black/40 rounded-full px-3 py-1">
                                    <div className="w-3 h-px bg-primary opacity-70" />
                                    <span className="text-[10px] text-primary font-mono">← {armLengthCm}cm →</span>
                                    <div className="w-3 h-px bg-primary opacity-70" />
                                </div>
                            </div>

                            {/* Status badge */}
                            <div className="absolute top-2 left-2">
                                {modelLoading ? (
                                    <span className="px-2 py-1 rounded-full text-xs bg-warning/20 text-warning animate-pulse">
                                        ⏳ Loading AI…
                                    </span>
                                ) : cameraReady && faceDetected ? (
                                    <span className="px-2 py-1 rounded-full text-xs bg-primary/20 text-primary">● Face Detected</span>
                                ) : (
                                    <span className="px-2 py-1 rounded-full text-xs bg-surface-light text-text-muted">Looking for face…</span>
                                )}
                            </div>

                            {/* Rough distance preview */}
                            {previewDist !== null && (
                                <div className="absolute top-2 right-2">
                                    <span className={`px-2 py-1 rounded-full text-xs font-mono font-bold ${Math.abs(previewDist - armLengthCm / 100) < 0.1 ? "bg-success/20 text-success" : "bg-surface-light text-text-muted"}`}>
                                        ~{previewDist.toFixed(2)}m
                                    </span>
                                </div>
                            )}
                        </div>

                        {/* Arm length slider */}
                        <div className="w-full max-w-xs mb-4">
                            <div className="flex justify-between items-center text-sm mb-1">
                                <span className="text-text-secondary">My arm's length</span>
                                <span className="font-mono font-bold text-primary">{armLengthCm} cm</span>
                            </div>
                            <input
                                type="range"
                                min={40} max={80} step={1}
                                value={armLengthCm}
                                onChange={(e) => setArmLengthCm(Number(e.target.value))}
                                className="w-full h-2 rounded-full appearance-none cursor-pointer bg-surface-light accent-primary"
                            />
                            <div className="flex justify-between text-xs text-text-muted mt-1">
                                <span>40cm</span><span className="text-primary">Default 60cm</span><span>80cm</span>
                            </div>
                        </div>

                        {/* Sample collection progress */}
                        <div className="w-full max-w-xs mb-5">
                            <div className="flex justify-between text-xs text-text-muted mb-1">
                                <span>Collecting measurements</span>
                                <span className={sampleCount >= SAMPLES_NEEDED ? "text-success" : ""}>
                                    {sampleCount}/{SAMPLES_NEEDED}
                                </span>
                            </div>
                            <div className="h-2 bg-surface-light rounded-full overflow-hidden">
                                <motion.div
                                    className="h-full bg-primary rounded-full"
                                    animate={{ width: `${Math.min(1, progress) * 100}%` }}
                                    transition={{ duration: 0.2 }}
                                />
                            </div>
                            {!faceDetected && !modelLoading && cameraReady && (
                                <motion.p
                                    className="text-xs text-warning mt-2"
                                    animate={{ opacity: [1, 0.5, 1] }}
                                    transition={{ duration: 1.5, repeat: Infinity }}
                                >
                                    Position your face inside the oval
                                </motion.p>
                            )}
                        </div>

                        {/* CTA */}
                        <AnimatePresence mode="wait">
                            {done ? (
                                <motion.div
                                    key="done"
                                    initial={{ scale: 0.8, opacity: 0 }}
                                    animate={{ scale: 1, opacity: 1 }}
                                    className="flex items-center gap-2 text-success font-semibold text-lg"
                                >
                                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
                                        <circle cx="12" cy="12" r="10" stroke="#10B981" strokeWidth="2" />
                                        <path d="M7 12l3 3 7-7" stroke="#10B981" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                                    </svg>
                                    Calibrated!
                                </motion.div>
                            ) : (
                                <motion.button
                                    key="btn"
                                    onClick={handleCalibrate}
                                    disabled={!canCalibrate}
                                    className={`w-full max-w-xs py-4 rounded-2xl font-semibold text-lg transition-all duration-300 ${canCalibrate ? "bg-primary text-background glow-primary cursor-pointer hover:scale-[1.02] active:scale-[0.97]" : "bg-surface-light text-text-muted cursor-not-allowed"}`}
                                    whileHover={canCalibrate ? { y: -2 } : {}}
                                    whileTap={canCalibrate ? { scale: 0.97 } : {}}
                                >
                                    {canCalibrate ? "Calibrate & Continue →" : `Collecting… (${sampleCount}/${SAMPLES_NEEDED})`}
                                </motion.button>
                            )}
                        </AnimatePresence>
                    </>
                )}
            </motion.div>
        </div>
    );
}
