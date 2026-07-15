"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { motion } from "framer-motion";
import { useAppStore } from "@/lib/store";
import { KalmanFilter } from "@/lib/kalman";
import {
    estimateFromIris,
    estimateFromIPD,
    estimateFromFaceWidth,
    fuseDistanceEstimates,
    autoEstimateFocalLength,
    type LandmarkPoint,
} from "@/lib/distance";
import { useHardwareWS, sendIPDToBackend } from "@/lib/hardware-ws";

export default function CameraSetupScreen() {
    const setScreen = useAppStore((s) => s.setScreen);
    const setDistance = useAppStore((s) => s.setDistance);
    const ipd = useAppStore((s) => s.ipd);
    const isMobile = useAppStore((s) => s.isMobile);

    const videoRef = useRef<HTMLVideoElement>(null);
    const canvasRef = useRef<HTMLCanvasElement>(null);
    const streamRef = useRef<MediaStream | null>(null);

    const [cameraReady, setCameraReady] = useState(false);
    const [faceDetected, setFaceDetected] = useState(false);
    const [currentDistance, setCurrentDistance] = useState(0);
    const [confidence, setConfidence] = useState(0);
    const [error, setError] = useState<string | null>(null);
    const [focalLength, setFocalLength] = useState<number>(0);

    const kalmanRef = useRef(new KalmanFilter(2.0, 0.005, 0.08));
    const faceMeshRef = useRef<any>(null);
    const initRef = useRef(false);
    const animFrameRef = useRef<number>(0);
    const [modelLoading, setModelLoading] = useState(true);

    // Pi hardware mode — WebSocket connection to Python backend
    const { piMode, faceDetected: piFaceDetected, faceCount, irisPx, previewUrl } = useHardwareWS();
    // Wait up to 1.5 s for WS probe before starting browser MediaPipe
    const [piProbeComplete, setPiProbeComplete] = useState(false);
    useEffect(() => {
        const t = setTimeout(() => setPiProbeComplete(true), 1600);
        return () => clearTimeout(t);
    }, []);

    // Read distance from store (works for both Pi and browser paths)
    const storeDistance = useAppStore((s) => s.distance);
    const storeConfidence = useAppStore((s) => s.distanceConfidence);

    // Effective values — Pi overrides browser
    // In Pi mode use the EMA-smoothed storeDistance (median+EMA pipeline in
    // ultrasonic.py gives responsive readings ~180ms while rejecting spikes).
    const effectiveFaceDetected = piMode ? piFaceDetected : faceDetected;
    const effectiveDistance = piMode ? storeDistance : currentDistance;
    const effectiveConfidence = piMode ? storeConfidence : confidence;

    // When Pi mode activates, mark camera ready immediately and send IPD
    useEffect(() => {
        if (!piMode) return;
        setCameraReady(true);
        setModelLoading(false);
        sendIPDToBackend(ipd);
        // Stop any browser camera that may have started during probe window
        cancelAnimationFrame(animFrameRef.current);
        if (streamRef.current) {
            streamRef.current.getTracks().forEach((t) => t.stop());
            streamRef.current = null;
        }
    }, [piMode, ipd]);

    // Load MediaPipe Face Mesh + camera with auto focal length
    useEffect(() => {
        // Skip if Pi backend is available or probe window not yet complete
        if (!piProbeComplete || piMode) return;
        // Guard against React StrictMode double-mount — MediaPipe WASM cannot be initialized twice
        if (initRef.current) return;
        initRef.current = true;

        let cancelled = false;

        async function loadFaceMesh() {
            try {
                // Camera API requires a secure context (HTTPS or localhost).
                // On plain HTTP (e.g. Android Chrome via local network), mediaDevices is undefined.
                if (!navigator.mediaDevices?.getUserMedia) {
                    setModelLoading(false);
                    setError(
                        "Camera access requires HTTPS. " +
                        "Please access this page over https:// — run \`npm run dev:https\` on the host machine."
                    );
                    return;
                }

                const faceMeshModule = await import("@mediapipe/face_mesh");

                const faceMesh = new faceMeshModule.FaceMesh({
                    locateFile: (file: string) =>
                        `https://cdn.jsdelivr.net/npm/@mediapipe/face_mesh/${file}`,
                });

                faceMesh.setOptions({
                    maxNumFaces: 1,
                    refineLandmarks: true,
                    minDetectionConfidence: 0.5,
                    minTrackingConfidence: 0.5,
                });

                faceMeshRef.current = faceMesh;

                // Start camera
                if (videoRef.current) {
                    const stream = await navigator.mediaDevices.getUserMedia({
                        video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 720 } },
                    });
                    if (cancelled) { stream.getTracks().forEach((t) => t.stop()); return; }
                    streamRef.current = stream;
                    videoRef.current.srcObject = stream;
                    try { await videoRef.current.play(); } catch (e: any) {
                        if (e.name === "AbortError") return; // interrupted by cleanup, safe to ignore
                        throw e;
                    }
                    if (cancelled) return;
                    setCameraReady(true);

                    // Use arm's-length calibrated focal length if available, else auto-estimate
                    const w = videoRef.current.videoWidth || 1280;
                    const calibratedFpx = useAppStore.getState().focalLengthPx;
                    const fPx = calibratedFpx > 0 ? calibratedFpx : autoEstimateFocalLength(stream, w);
                    setFocalLength(fPx);

                    console.log('[Camera Setup] Focal length:', {
                        calibratedFpx,
                        usingCalibrated: calibratedFpx > 0,
                        finalFpx: fPx.toFixed(1),
                        videoWidth: w,
                    });

                    // Set up face mesh results handler with the auto-calibrated focal length
                    faceMesh.onResults((results: any) => {
                        if (cancelled) return;

                        if (results.multiFaceLandmarks && results.multiFaceLandmarks.length > 0) {
                            const landmarks: LandmarkPoint[] = results.multiFaceLandmarks[0];
                            setFaceDetected(true);
                            drawFaceMesh(landmarks);

                            if (fPx > 0 && videoRef.current) {
                                const vw = videoRef.current.videoWidth;
                                const vh = videoRef.current.videoHeight;

                                const estimates = [
                                    estimateFromIris(landmarks, fPx, vw, vh),
                                    estimateFromIPD(landmarks, fPx, ipd, vw, vh),
                                    estimateFromFaceWidth(landmarks, fPx, vw, vh),
                                ].filter(Boolean) as any[];

                                if (estimates.length > 0) {
                                    const fused = fuseDistanceEstimates(estimates);
                                    const filtered = kalmanRef.current.update(fused.distance);
                                    setCurrentDistance(filtered);
                                    setConfidence(fused.confidence);
                                    setDistance(filtered, fused.distance, fused.confidence);
                                }
                            }
                        } else {
                            setFaceDetected(false);
                        }
                    });

                    // Download and initialize the MediaPipe WASM model (~12MB from CDN)
                    await faceMesh.initialize();
                    if (cancelled) return;
                    setModelLoading(false);

                    // Pump video frames into FaceMesh via requestAnimationFrame
                    function pump() {
                        if (cancelled) return;
                        if (faceMeshRef.current && videoRef.current) {
                            faceMeshRef.current.send({ image: videoRef.current }).catch(() => { });
                        }
                        animFrameRef.current = requestAnimationFrame(pump);
                    }
                    pump();
                }
            } catch (err: any) {
                if (!cancelled) {
                    setModelLoading(false);
                    setError(err.message || "Failed to start camera");
                }
            }
        }

        loadFaceMesh();

        return () => {
            cancelled = true;
            initRef.current = false; // allow re-init on remount ("Test Again")
            cancelAnimationFrame(animFrameRef.current);
            if (streamRef.current) {
                streamRef.current.getTracks().forEach((t) => t.stop());
            }
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [piProbeComplete, piMode]);

    // Draw face mesh wireframe on canvas
    const drawFaceMesh = useCallback((landmarks: LandmarkPoint[]) => {
        const canvas = canvasRef.current;
        const video = videoRef.current;
        if (!canvas || !video) return;

        const ctx = canvas.getContext("2d");
        if (!ctx) return;

        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        const keyPoints = [
            10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378,
            400, 377, 152, 148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21,
            54, 103, 67, 109,
            33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246,
            362, 382, 381, 380, 374, 373, 390, 249, 263, 466, 388, 387, 386, 385, 384, 398,
            468, 469, 470, 471, 472, 473, 474, 475, 476, 477,
        ];

        for (const idx of keyPoints) {
            if (idx < landmarks.length) {
                const lm = landmarks[idx];
                const x = lm.x * canvas.width;
                const y = lm.y * canvas.height;
                const isIris = idx >= 468;
                ctx.beginPath();
                ctx.arc(x, y, isIris ? 2.5 : 1.5, 0, Math.PI * 2);
                ctx.fillStyle = isIris ? "rgba(99, 102, 241, 0.9)" : "rgba(0, 212, 170, 0.5)";
                ctx.fill();
            }
        }

        if (landmarks.length >= 478) {
            for (const centerIdx of [468, 473]) {
                const center = landmarks[centerIdx];
                const cx = center.x * canvas.width;
                const cy = center.y * canvas.height;
                const boundaryIdx = centerIdx === 468 ? 469 : 474;
                const boundary = landmarks[boundaryIdx];
                const bx = boundary.x * canvas.width;
                const by = boundary.y * canvas.height;
                const r = Math.sqrt((cx - bx) ** 2 + (cy - by) ** 2);

                ctx.beginPath();
                ctx.arc(cx, cy, r, 0, Math.PI * 2);
                ctx.strokeStyle = "rgba(99, 102, 241, 0.7)";
                ctx.lineWidth = 1.5;
                ctx.stroke();
            }
        }
    }, []);

    const handleStartTest = () => {
        // Stop camera before navigating — avoids dual-stream conflict with TestScreen
        cancelAnimationFrame(animFrameRef.current);
        if (streamRef.current) {
            streamRef.current.getTracks().forEach((t) => t.stop());
            streamRef.current = null;
        }
        setScreen("test");
    };

    const distanceColor =
        effectiveDistance < 1.5
            ? "text-danger"
            : effectiveDistance < 2
                ? "text-warning"
                : "text-success";

    const distanceBarWidth = Math.min(100, Math.max(0, (effectiveDistance / (isMobile ? 3 : 6)) * 100));
    const isReady = cameraReady && !modelLoading && effectiveFaceDetected && effectiveDistance > 0.3;

    return (
        <div className="flex min-h-screen flex-col items-center justify-center px-6">
            {/* Progress bar */}
            <div className="fixed top-0 left-0 right-0 h-1 bg-surface z-50">
                <motion.div
                    className="h-full bg-primary"
                    initial={{ width: "66%" }}
                    animate={{ width: "100%" }}
                    transition={{ duration: 0.6 }}
                />
            </div>

            <motion.div
                className="max-w-2xl w-full flex flex-col items-center"
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5 }}
            >
                <p className="text-sm text-text-muted mb-2 font-medium tracking-wide uppercase">
                    Step {isMobile ? "4 of 4" : "3 of 3"}
                </p>
                <h2 className="text-3xl font-bold mb-2 text-center">Camera Setup</h2>
                <p className="text-sm text-text-secondary mb-6 text-center max-w-md">
                    Position yourself in front of the camera. Distance is measured automatically using face detection.
                </p>

                {error && (
                    <div className="bg-danger/20 border border-danger/30 rounded-xl p-4 mb-6 text-danger text-sm">
                        {error}
                    </div>
                )}

                {/* Camera feed — Pi mode streams JPEG preview; browser mode shows video */}
                <div className="relative w-full aspect-video rounded-2xl overflow-hidden bg-surface mb-6 border border-white/5">
                    {piMode ? (
                        previewUrl ? (
                            /* Live JPEG stream from Pi camera */
                            // eslint-disable-next-line @next/next/no-img-element
                            <img
                                src={previewUrl}
                                alt="Pi Camera"
                                className="absolute inset-0 w-full h-full object-cover -scale-x-100"
                            />
                        ) : (
                            /* Waiting for first frame */
                            <div className="absolute inset-0 flex flex-col items-center justify-center gap-4">
                                <div className="w-20 h-20 rounded-full bg-primary/10 border-2 border-primary/40 flex items-center justify-center animate-pulse">
                                    <svg width="36" height="36" viewBox="0 0 36 36" fill="none">
                                        <circle cx="18" cy="18" r="10" stroke="#00D4AA" strokeWidth="2" fill="none" />
                                        <circle cx="18" cy="18" r="4" fill="#00D4AA" />
                                        <rect x="14" y="6" width="8" height="4" rx="2" fill="#00D4AA" opacity="0.6" />
                                    </svg>
                                </div>
                                <p className="text-primary font-semibold">Pi Camera Active</p>
                                <p className="text-xs text-text-muted">Waiting for preview...</p>
                            </div>
                        )
                    ) : (
                        <>
                            <video
                                ref={videoRef}
                                className="absolute inset-0 w-full h-full object-cover -scale-x-100"
                                playsInline
                                muted
                            />
                            <canvas
                                ref={canvasRef}
                                className="absolute inset-0 w-full h-full object-cover -scale-x-100 pointer-events-none"
                            />
                        </>
                    )}

                    {/* Face guide oval — shown when no face detected yet */}
                    {!effectiveFaceDetected && cameraReady && (piMode ? !!previewUrl : true) && (
                        <div className="absolute inset-0 flex items-center justify-center">
                            <div className="w-40 h-56 border-2 border-dashed border-primary/40 rounded-full animate-pulse-glow" />
                        </div>
                    )}

                    {/* Status badges */}
                    <div className="absolute top-4 left-4 flex gap-2 flex-wrap">
                        <span className={`px-3 py-1 rounded-full text-xs font-medium ${cameraReady ? "bg-success/20 text-success" : piProbeComplete ? "bg-warning/20 text-warning" : "bg-surface-light text-text-muted"}`}>
                            {piMode ? "● Pi Camera" : cameraReady ? "● Camera Active" : piProbeComplete ? "⏳ Starting Camera..." : "⏳ Detecting mode..."}
                        </span>
                        {!piMode && cameraReady && modelLoading && (
                            <span className="px-3 py-1 rounded-full text-xs font-medium bg-warning/20 text-warning animate-pulse">
                                ⏳ Loading AI model...
                            </span>
                        )}
                        {effectiveFaceDetected && !modelLoading && (
                            <span className="px-3 py-1 rounded-full text-xs font-medium bg-primary/20 text-primary">
                                ● Face Detected
                            </span>
                        )}
                        {piMode && faceCount > 1 && (
                            <span className="px-3 py-1 rounded-full text-xs font-medium bg-danger/20 text-danger">
                                Multiple Faces
                            </span>
                        )}
                    </div>

                    {/* Distance overlay */}
                    {effectiveDistance > 0 && (
                        <div className="absolute bottom-4 right-4 glass rounded-xl px-4 py-2">
                            <span className={`text-2xl font-mono font-bold ${distanceColor}`}>
                                {effectiveDistance.toFixed(2)}m
                            </span>
                        </div>
                    )}
                </div>

                {/* Distance readout bar */}
                {effectiveDistance > 0 && (
                    <motion.div
                        className="w-full max-w-md mb-6"
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                    >
                        <div className="flex items-center justify-between mb-2">
                            <span className="text-sm text-text-secondary">Distance</span>
                            <span className={`text-xl font-mono font-bold ${distanceColor}`}>
                                {effectiveDistance.toFixed(2)}m
                            </span>
                        </div>
                        <div className="h-3 bg-surface-light rounded-full overflow-hidden">
                            <motion.div
                                className="h-full rounded-full"
                                style={{
                                    background:
                                        effectiveDistance < 1.5 ? "#EF4444" : effectiveDistance < 2 ? "#F59E0B" : "#10B981",
                                }}
                                animate={{ width: `${distanceBarWidth}%` }}
                                transition={{ duration: 0.1 }}
                            />
                        </div>
                        <div className="flex justify-between text-xs text-text-muted mt-1">
                            <span>0m</span>
                            <span className="text-primary">Optimal: {isMobile ? "0.5–1.5m" : "2–5m"}</span>
                            <span>{isMobile ? "3m" : "6m"}</span>
                        </div>
                    </motion.div>
                )}

                {/* Auto-calibration info */}
                {(piMode ? irisPx : focalLength) !== null && cameraReady && (
                    <motion.div
                        className="text-xs text-text-muted mb-4 text-center font-mono"
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        transition={{ delay: 0.5 }}
                    >
                        {piMode
                            ? `Pi Camera · iris=${irisPx?.toFixed(1) ?? "--"}px · Conf: ${(effectiveConfidence * 100).toFixed(0)}%`
                            : `Auto-calibrated · f=${Math.round(focalLength)}px · Conf: ${(effectiveConfidence * 100).toFixed(0)}%`}
                    </motion.div>
                )}

                {/* Start test button */}
                <motion.button
                    onClick={handleStartTest}
                    disabled={!isReady}
                    className={`px-10 py-4 rounded-2xl font-semibold text-lg transition-all duration-300 cursor-pointer ${isReady ? "bg-primary text-background glow-primary glow-primary-hover hover:scale-[1.02]" : "bg-surface-light text-text-muted cursor-not-allowed"}`}
                    whileHover={isReady ? { y: -2 } : {}}
                    whileTap={isReady ? { scale: 0.97 } : {}}
                >
                    {!cameraReady
                        ? (!piProbeComplete ? "Detecting Pi mode..." : "Starting camera...")
                        : modelLoading ? "Loading AI model..."
                            : isReady ? "Start Vision Test →"
                                : "Detecting face..."}
                </motion.button>
            </motion.div>
        </div>
    );
}

