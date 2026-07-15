"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
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
import { useHardwareWS } from "@/lib/hardware-ws";
import {
    optotypeHeightPx,
    smartRandomDirection,
    directionToRotation,
} from "@/lib/optotype";
import {
    ACUITY_LEVELS,
    STABILITY_DISTANCE_THRESHOLD_CM,
    STABILITY_LOCK_DURATION_S,
    MIN_CORRECT_TO_ADVANCE,
    MAX_WRONG_TO_TERMINATE,
    LOGMAR_CEILING,
} from "@/lib/constants";
import type { StabilityState, EDirection, TestResponse, TestResult, CheatFlag } from "@/lib/types";

export default function TestScreen() {
    const store = useAppStore();
    const {
        calibration,
        ipd,
        setScreen,
        stability,
        setStability,
        lockedDistance,
        setLockedDistance,
        stabilityTimer,
        setStabilityTimer,
        currentLevelIndex,
        currentTrialIndex,
        currentDirection,
        setCurrentLevel,
        setCurrentTrial,
        setCurrentDirection,
        addResponse,
        responses,
        testStartTime,
        setTestStartTime,
        setTestResult,
        setDistance,
    } = store;
    const isMobile = useAppStore((s) => s.isMobile);
    const optotypeType = useAppStore((s) => s.optotypeType);

    const videoRef = useRef<HTMLVideoElement>(null);
    const canvasRef = useRef<HTMLCanvasElement>(null);
    const streamRef = useRef<MediaStream | null>(null);
    const faceMeshRef = useRef<any>(null);

    const kalmanRef = useRef(new KalmanFilter(2.0, 0.005, 0.08));
    const stabilityAnchorRef = useRef(0);
    const stabilityStartRef = useRef(0);
    const initRef = useRef(false);
    const animFrameRef = useRef<number>(0);

    // Pi hardware mode
    const { piMode, faceDetected: piFaceDetected, faceCount: piFaceCount, attentionOk: piAttentionOk, attentionReason: piAttentionReason, previewUrl: piPreviewUrl } = useHardwareWS();
    const piProbeCompleteRef = useRef(false);
    useEffect(() => {
        const t = setTimeout(() => { piProbeCompleteRef.current = true; }, 1600);
        return () => clearTimeout(t);
    }, []);
    // Cheating prevention refs
    const cheatingFlagsRef = useRef<CheatFlag[]>([]);
    const trialStartRef = useRef(Date.now());
    const lastFaceSeenRef = useRef(Date.now());
    const faceLostFlaggedRef = useRef(false);
    const multiFaceFlaggedRef = useRef(false);
    const wakeLockRef = useRef<any>(null);
    // distRef is written directly by the face-mesh callback so the stability
    // interval (which has empty deps) always reads the freshest value.
    const distRef = useRef(0);
    // Ref mirror of piAttentionOk so the keyboard handler closure always reads
    // the latest value without needing to be re-created on every attention change.
    const piAttentionOkRef = useRef(true);
    useEffect(() => { piAttentionOkRef.current = piAttentionOk; }, [piAttentionOk]);

    const [currentFilteredDist, setCurrentFilteredDist] = useState(0);
    const [focalLength, setFocalLength] = useState(0);
    const [cameraActive, setCameraActive] = useState(false);
    const [showFeedback, setShowFeedback] = useState<"correct" | "wrong" | null>(null);

    // Gyro state
    const [gyroAvailable, setGyroAvailable] = useState(false);
    const [gyroPermissionRequested, setGyroPermissionRequested] = useState(false);
    const lastGyroRef = useRef({ alpha: 0, beta: 0, gamma: 0 });
    const gyroAnchorRef = useRef({ alpha: 0, beta: 0, gamma: 0 });

    // Request gyro permission on mobile
    useEffect(() => {
        if (!isMobile) return;
        // iOS 13+ requires explicit permission
        if (typeof DeviceOrientationEvent !== 'undefined' &&
            typeof (DeviceOrientationEvent as any).requestPermission === 'function') {
            // Wait for user interaction
            setGyroPermissionRequested(false);
        } else {
            // Android or desktop: permission not required
            setGyroPermissionRequested(true);
        }
    }, [isMobile]);

    // Handler for requesting permission
    const requestGyroPermission = async () => {
        if (typeof DeviceOrientationEvent !== 'undefined' &&
            typeof (DeviceOrientationEvent as any).requestPermission === 'function') {
            try {
                const response = await (DeviceOrientationEvent as any).requestPermission();
                if (response === 'granted') {
                    setGyroPermissionRequested(true);
                }
            } catch (err) {
                alert('Gyroscope permission denied.');
            }
        } else {
            setGyroPermissionRequested(true);
        }
    };

    const currentLevel = ACUITY_LEVELS[currentLevelIndex];
    const mmPerPx = calibration?.mmPerPx ?? 0.25; // fallback

    // Initialize test
    useEffect(() => {
        setTestStartTime(Date.now());
        setCurrentDirection(smartRandomDirection());
    }, [setTestStartTime, setCurrentDirection]);

    // WakeLock: keep screen on during test
    useEffect(() => {
        async function acquire() {
            if ("wakeLock" in navigator) {
                try { wakeLockRef.current = await (navigator as any).wakeLock.request("screen"); } catch { /* denied */ }
            }
        }
        acquire();
        return () => { wakeLockRef.current?.release().catch(() => { }); };
    }, []);

    // Fullscreen: enter on mount, log exits as cheat events
    useEffect(() => {
        if (document.documentElement.requestFullscreen) {
            document.documentElement.requestFullscreen().catch(() => { });
        }
        const onFSChange = () => {
            if (!document.fullscreenElement) {
                cheatingFlagsRef.current.push({ type: "fullscreen_exit", timestamp: Date.now() });
            }
        };
        document.addEventListener("fullscreenchange", onFSChange);
        return () => {
            document.removeEventListener("fullscreenchange", onFSChange);
            if (document.fullscreenElement) document.exitFullscreen().catch(() => { });
        };
    }, []);

    // Tab visibility: log tab switches as cheat events
    useEffect(() => {
        const onVisibility = () => {
            if (document.hidden) {
                cheatingFlagsRef.current.push({ type: "tab_switch", timestamp: Date.now() });
            }
        };
        document.addEventListener("visibilitychange", onVisibility);
        return () => document.removeEventListener("visibilitychange", onVisibility);
    }, []);

    // Track when each trial starts for fast-answer detection
    useEffect(() => {
        trialStartRef.current = Date.now();
    }, [currentDirection]);

    // Sync Pi distance into distRef (replaces browser MediaPipe path when piMode)
    const piStoreDistance = useAppStore((s) => s.distance);
    const piDistanceConfidence = useAppStore((s) => s.distanceConfidence);
    useEffect(() => {
        if (!piMode) return;
        // Only accept a reading when the ultrasonic sensor is genuinely active
        // (confidence=1.0). When sensor is disconnected, confidence=0 and
        // distance=0 — reset distRef so the stability FSM stops and the test
        // cannot proceed with stale or fabricated distance data.
        if (piStoreDistance > 0 && piDistanceConfidence >= 0.5) {
            distRef.current = piStoreDistance;
            setCurrentFilteredDist(piStoreDistance);
        } else {
            distRef.current = 0;
            setCurrentFilteredDist(0);
        }
    }, [piMode, piStoreDistance, piDistanceConfidence]);

    // Keep lastFaceSeenRef current in Pi mode.
    // Use attentionOk rather than faceDetected: only counts as "seen" when the
    // user is correctly positioned and looking at the screen.
    useEffect(() => {
        if (!piMode || !piAttentionOk) return;
        lastFaceSeenRef.current = Date.now();
    }, [piMode, piAttentionOk]);

    // Start camera + face mesh
    useEffect(() => {
        // Skip if Pi backend is handling face detection
        if (piMode) { setCameraActive(true); return; }
        // Guard against React StrictMode double-mount — MediaPipe WASM cannot be initialized twice
        if (initRef.current) return;
        initRef.current = true;

        let cancelled = false;

        async function startCamera() {
            try {
                if (!navigator.mediaDevices?.getUserMedia) {
                    console.error("Camera requires HTTPS or localhost. Access this page over https://");
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

                if (videoRef.current) {
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
                    setCameraActive(true);

                    // Use arm's-length calibrated focal length if available, else auto-estimate
                    const vw = videoRef.current.videoWidth || 1280;
                    const _calibFpx = useAppStore.getState().focalLengthPx;
                    const fPx = _calibFpx > 0 ? _calibFpx : autoEstimateFocalLength(stream, vw);
                    setFocalLength(fPx);

                    console.log('[Test Screen] Focal length:', {
                        calibratedFpx: _calibFpx,
                        usingCalibrated: _calibFpx > 0,
                        finalFpx: fPx.toFixed(1),
                        videoWidth: vw,
                    });

                    faceMesh.onResults((results: any) => {
                        if (cancelled) return;
                        const storeIpd = useAppStore.getState().ipd;

                        // Cheating: multiple faces in frame
                        if ((results.multiFaceLandmarks?.length ?? 0) > 1) {
                            if (!multiFaceFlaggedRef.current) {
                                multiFaceFlaggedRef.current = true;
                                cheatingFlagsRef.current.push({ type: "multiple_faces", timestamp: Date.now() });
                            }
                        } else {
                            multiFaceFlaggedRef.current = false;
                        }

                        if (results.multiFaceLandmarks?.length > 0 && fPx > 0 && videoRef.current) {
                            lastFaceSeenRef.current = Date.now(); // for face-lost detection
                            const landmarks: LandmarkPoint[] = results.multiFaceLandmarks[0];
                            const w = videoRef.current.videoWidth;
                            const h = videoRef.current.videoHeight;

                            const estimates = [
                                estimateFromIris(landmarks, fPx, w, h),
                                estimateFromIPD(landmarks, fPx, storeIpd, w, h),
                                estimateFromFaceWidth(landmarks, fPx, w, h),
                            ].filter(Boolean) as any[];

                            if (estimates.length > 0) {
                                const fused = fuseDistanceEstimates(estimates);
                                const filtered = kalmanRef.current.update(fused.distance);
                                distRef.current = filtered; // keep ref in sync for stability interval
                                setCurrentFilteredDist(filtered);
                                useAppStore.getState().setDistance(filtered, fused.distance, fused.confidence);
                            }
                        }
                    });

                    await faceMesh.initialize();
                    if (cancelled) return;

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
            } catch (err) {
                console.error("Camera error:", err);
            }
        }

        startCamera();

        return () => {
            cancelled = true;
            cancelAnimationFrame(animFrameRef.current);
            if (streamRef.current) {
                streamRef.current.getTracks().forEach((t) => t.stop());
            }
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [piMode]);

    // Gyroscope listener (only after permission)
    useEffect(() => {
        if (!gyroPermissionRequested) return;
        const handleOrientation = (e: DeviceOrientationEvent) => {
            if (e.alpha !== null) {
                setGyroAvailable(true);
                lastGyroRef.current = {
                    alpha: e.alpha ?? 0,
                    beta: e.beta ?? 0,
                    gamma: e.gamma ?? 0,
                };
            }
        };

        window.addEventListener("deviceorientation", handleOrientation);
        return () => window.removeEventListener("deviceorientation", handleOrientation);
    }, [gyroPermissionRequested]);

    // Stability guard FSM.
    //
    // KEY FIX: empty dep array so the interval is created ONCE and never torn down.
    // The old code had [currentFilteredDist] in deps — face-mesh fires at ~30 fps so the
    // interval was reset every ~33 ms and its 100 ms tick NEVER fired.
    //
    // Distance is read from distRef (written directly by the face-mesh callback),
    // and store state is read via getState() — both patterns avoid stale closures.
    useEffect(() => {
        // Start every test with a clean state
        useAppStore.getState().setStability("LOCKED");
        useAppStore.getState().setStabilityTimer(STABILITY_LOCK_DURATION_S);
        stabilityAnchorRef.current = 0;

        const interval = setInterval(() => {
            const dist = distRef.current;
            if (dist <= 0) return;

            const { stability: stab, lockedDistance: locked } = useAppStore.getState();

            if (stab === "LOCKED") {
                if (stabilityAnchorRef.current === 0) stabilityAnchorRef.current = dist;

                const drift = Math.abs(dist - stabilityAnchorRef.current) * 100; // cm

                // Fast EMA so anchor tracks the user's new position quickly.
                // 0.6/0.4 converges in ~3 ticks (450 ms) vs 0.8/0.2 (>1 s).
                stabilityAnchorRef.current = 0.6 * stabilityAnchorRef.current + 0.4 * dist;

                if (drift < 15) {
                    // Position looks stable — start 3-second countdown
                    stabilityStartRef.current = Date.now();
                    useAppStore.getState().setStability("STABILIZING");
                    useAppStore.getState().setStabilityTimer(STABILITY_LOCK_DURATION_S);
                }
            } else if (stab === "STABILIZING") {
                const drift = Math.abs(dist - stabilityAnchorRef.current) * 100;

                if (drift > 10) {
                    // Moved during countdown — reset immediately
                    useAppStore.getState().setStability("LOCKED");
                    stabilityAnchorRef.current = dist;
                    useAppStore.getState().setStabilityTimer(STABILITY_LOCK_DURATION_S);
                } else {
                    // Gentle drift during countdown is fine
                    stabilityAnchorRef.current = 0.97 * stabilityAnchorRef.current + 0.03 * dist;
                    const elapsed = (Date.now() - stabilityStartRef.current) / 1000;
                    const remaining = Math.max(0, STABILITY_LOCK_DURATION_S - elapsed);
                    useAppStore.getState().setStabilityTimer(remaining);
                    if (elapsed >= STABILITY_LOCK_DURATION_S) {
                        useAppStore.getState().setStability("UNLOCKED");
                        useAppStore.getState().setLockedDistance(stabilityAnchorRef.current);
                    }
                }
            } else if (stab === "UNLOCKED") {
                // Continuously refresh lastFaceSeenRef while face is present.
                // Without this, the ref only updates on piAttentionOk TRANSITIONS
                // (false→true), so after 2s of continuous face detection the
                // face_lost flag fires even with a face right there.
                if (piAttentionOkRef.current) {
                    lastFaceSeenRef.current = Date.now();
                }

                const drift = Math.abs(dist - locked) * 100;
                if (drift > 10) {
                    // > 10 cm drift — reset immediately.
                    // Median+EMA pipeline reflects real moves within ~180 ms,
                    // so this triggers in near-real-time on any deliberate movement.
                    useAppStore.getState().setStability("LOCKED");
                    stabilityAnchorRef.current = dist;
                    useAppStore.getState().setStabilityTimer(STABILITY_LOCK_DURATION_S);
                }
                // Face-lost cheating detection (face absent for > 2s while test is active)
                const msSinceFace = Date.now() - lastFaceSeenRef.current;
                if (msSinceFace > 2000) {
                    if (!faceLostFlaggedRef.current) {
                        faceLostFlaggedRef.current = true;
                        cheatingFlagsRef.current.push({ type: "face_lost", timestamp: Date.now(), detail: `${Math.round(msSinceFace / 1000)}s` });
                    }
                } else {
                    faceLostFlaggedRef.current = false;
                }
            }
        }, 150);

        return () => clearInterval(interval);
    }, []); // eslint-disable-line react-hooks/exhaustive-deps

    // Keyboard listener for arrow keys (works with ESP32 BLE HID)
    useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent) => {
            if (stability !== "UNLOCKED") return;
            // In Pi mode: block input when attention monitor says user isn't engaged
            if (piMode && !piAttentionOkRef.current) return;

            let answered: EDirection | null = null;
            switch (e.key) {
                case "ArrowUp": answered = "up"; break;
                case "ArrowDown": answered = "down"; break;
                case "ArrowLeft": answered = "left"; break;
                case "ArrowRight": answered = "right"; break;
            }

            if (answered) {
                e.preventDefault();
                handleAnswer(answered);
            }
        };

        window.addEventListener("keydown", handleKeyDown);
        return () => window.removeEventListener("keydown", handleKeyDown);
    }, [stability, currentDirection, currentLevelIndex, currentTrialIndex]);

    // Handle patient's answer
    const handleAnswer = useCallback(
        (answered: EDirection) => {
            // Block answers when Pi attention monitor says user isn't engaged
            if (piMode && !piAttentionOkRef.current) return;
            const correct = answered === currentDirection;
            const level = ACUITY_LEVELS[currentLevelIndex];

            // Cheating: suspiciously fast answer (< 300ms is physiologically impossible)
            const latencyMs = Date.now() - trialStartRef.current;
            if (latencyMs < 300) {
                cheatingFlagsRef.current.push({ type: "fast_answer", timestamp: Date.now(), detail: `${latencyMs}ms` });
            }

            // Haptic feedback on mobile
            if (typeof navigator !== "undefined" && navigator.vibrate) {
                navigator.vibrate(correct ? 40 : [40, 60, 40]);
            }

            const response: TestResponse = {
                level,
                trialIndex: currentTrialIndex,
                presented: currentDirection,
                answered,
                correct,
                timestamp: Date.now(),
                distance: lockedDistance,
            };

            addResponse(response);

            // Show feedback
            setShowFeedback(correct ? "correct" : "wrong");
            setTimeout(() => setShowFeedback(null), 400);

            const allResponses = [...responses, response];
            const levelResponses = allResponses.filter(
                (r) => r.level.logMAR === level.logMAR
            );
            const correctCount = levelResponses.filter((r) => r.correct).length;
            const wrongCount = levelResponses.filter((r) => !r.correct).length;

            const nextTrial = currentTrialIndex + 1;

            // Check if level is complete
            if (nextTrial >= level.trialsPerLevel) {
                if (correctCount >= MIN_CORRECT_TO_ADVANCE) {
                    // Advance to next (harder) level
                    const nextLevel = currentLevelIndex + 1;
                    if (nextLevel >= ACUITY_LEVELS.length) {
                        // Test complete — best possible acuity
                        finishTest(allResponses);
                    } else {
                        setCurrentLevel(nextLevel);
                        setCurrentTrial(0);
                        setCurrentDirection(smartRandomDirection(currentDirection));
                    }
                } else {
                    // Failed this level — test complete at previous level
                    finishTest(allResponses);
                }
            } else if (wrongCount >= MAX_WRONG_TO_TERMINATE) {
                // Too many wrong — terminate this level early
                finishTest(allResponses);
            } else {
                // Next trial in same level
                setCurrentTrial(nextTrial);
                setCurrentDirection(smartRandomDirection(currentDirection));
            }
        },
        [
            currentDirection, currentLevelIndex, currentTrialIndex, lockedDistance,
            responses, addResponse, setCurrentLevel, setCurrentTrial, setCurrentDirection,
        ]
    );

    const finishTest = (allResponses: TestResponse[]) => {
        // Calculate per-level scores
        const perLevelScores = ACUITY_LEVELS.map((level) => {
            const lr = allResponses.filter((r) => r.level.logMAR === level.logMAR);
            return {
                level,
                correct: lr.filter((r) => r.correct).length,
                total: lr.length,
            };
        }).filter((s) => s.total > 0);

        // Best acuity = lowest logMAR with >= MIN_CORRECT_TO_ADVANCE correct
        let bestLevel = ACUITY_LEVELS[0]; // default 20/200
        for (const score of perLevelScores) {
            if (score.correct >= MIN_CORRECT_TO_ADVANCE) {
                bestLevel = score.level;
            }
        }

        // ── ETDRS fractional LogMAR (Ferris et al., ETDRS Report #13, 1982) ─────────
        // Uniform 0.1 LogMAR steps → every correct letter = exactly 0.02 LogMAR
        // Formula: acuity = LOGMAR_CEILING(1.1) − 0.02 × totalCorrectLetters
        const totalCorrect = perLevelScores.reduce((sum, s) => sum + s.correct, 0);
        const fractionalLogMAR = Math.round((LOGMAR_CEILING - 0.02 * totalCorrect) * 1000) / 1000;

        // ETDRS letter score — primary metric in clinical ophthalmology trials (0–70)
        const etdrsLetterScore = totalCorrect;

        // 95% CI: ±0.1 LogMAR (±1 line) — ETDRS empirical test-retest repeatability
        const CI_HALF_WIDTH = 0.1;

        // WHO ICD-11 visual impairment classification
        const whoClassification =
            fractionalLogMAR < 0.3 ? "Normal vision" :
                fractionalLogMAR < 0.5 ? "Mild impairment" :
                    fractionalLogMAR < 1.0 ? "Moderate impairment" :
                        fractionalLogMAR < 1.3 ? "Severe impairment" :
                            "Profound impairment";

        // Decimal VA: 20 / snellenDenominator (standard in Indian ophthalmology)
        const snellenDenom = parseFloat(bestLevel.snellen.split("/")[1] ?? "20");
        const decimalVA = Math.round((20 / snellenDenom) * 100) / 100;

        // Ambient light estimation from live camera feed (average luminance 0–255)
        let ambientLightEstimate = 0;
        if (videoRef.current && videoRef.current.readyState >= 2) {
            try {
                const tmpCanvas = document.createElement("canvas");
                tmpCanvas.width = 80;
                tmpCanvas.height = 45;
                const ctx2 = tmpCanvas.getContext("2d");
                if (ctx2) {
                    ctx2.drawImage(videoRef.current, 0, 0, 80, 45);
                    const pixels = ctx2.getImageData(0, 0, 80, 45).data;
                    let lumSum = 0;
                    for (let i = 0; i < pixels.length; i += 4) {
                        lumSum += 0.299 * pixels[i] + 0.587 * pixels[i + 1] + 0.114 * pixels[i + 2];
                    }
                    ambientLightEstimate = Math.round(lumSum / (80 * 45));
                }
            } catch { /* canvas security error — skip */ }
        }

        // Clinical metadata from pre-test form
        const { eyeTested: eyeTestedVal, correctionStatus: correctionStatusVal, patientInfo: patientInfoVal } = useAppStore.getState();

        const result: TestResult = {
            acuitySnellen: bestLevel.snellen,
            acuityLogMAR: bestLevel.logMAR,
            fractionalLogMAR,
            etdrsLetterScore,
            whoClassification,
            decimalVA,
            eyeTested: eyeTestedVal,
            correctionStatus: correctionStatusVal,
            patientInfo: patientInfoVal,
            ambientLightEstimate,
            confidenceInterval: {
                lower: Math.round((fractionalLogMAR - CI_HALF_WIDTH) * 1000) / 1000,
                upper: Math.round((fractionalLogMAR + CI_HALF_WIDTH) * 1000) / 1000,
                confidence: 0.95,
            },
            responses: allResponses,
            testDistance: lockedDistance,
            testDuration: Date.now() - testStartTime,
            date: new Date().toISOString(),
            perLevelScores,
            cheatingFlags: cheatingFlagsRef.current,
        };

        setTestResult(result);

        // Stop camera
        if (streamRef.current) {
            streamRef.current.getTracks().forEach((t) => t.stop());
        }

        setScreen("results");
    };

    // Calculate E size.
    // During positioning (LOCKED/STABILIZING): size to live currentFilteredDist so
    // the user can see the E responding to their distance — confirms the sensor works.
    // During test (UNLOCKED): size to lockedDistance which stays fixed for accuracy.
    const displayDistance = stability === "UNLOCKED"
        ? lockedDistance
        : (currentFilteredDist > 0 ? currentFilteredDist : lockedDistance);
    const eHeightPx =
        displayDistance > 0 && currentLevel
            ? optotypeHeightPx(displayDistance, currentLevel.arcMinPerStroke, mmPerPx)
            : 100;

    const eRotation = directionToRotation(currentDirection);
    const eStrokeWidth = eHeightPx / 5;

    // Movement/tilt detection for instant lock/blur
    const [movementLocked, setMovementLocked] = useState(false);
    const movementAnchorRef = useRef<number | null>(null);
    const tiltAnchorRef = useRef<{ alpha: number, beta: number, gamma: number } | null>(null);

    // Monitor distance and gyro for movement
    useEffect(() => {
        if (!gyroAvailable || !gyroPermissionRequested) return;
        // Set anchors on first unlock
        if (stability === "UNLOCKED" && movementAnchorRef.current === null) {
            movementAnchorRef.current = currentFilteredDist;
            tiltAnchorRef.current = { ...lastGyroRef.current };
        }
        // Only check when unlocked
        if (stability === "UNLOCKED" && movementAnchorRef.current !== null && tiltAnchorRef.current !== null) {
            // Distance check
            const distDrift = Math.abs(currentFilteredDist - movementAnchorRef.current) * 100; // cm
            // Tilt check (change in beta/gamma > threshold)
            const tiltDrift = Math.abs(lastGyroRef.current.beta - tiltAnchorRef.current.beta) + Math.abs(lastGyroRef.current.gamma - tiltAnchorRef.current.gamma);
            if (distDrift > 5 || tiltDrift > 15) {
                setMovementLocked(true);
            } else {
                setMovementLocked(false); // Resume when user returns to original position
            }
        }
        // Reset lock if stability changes
        if (stability !== "UNLOCKED") {
            setMovementLocked(false);
            movementAnchorRef.current = null;
            tiltAnchorRef.current = null;
        }
    }, [currentFilteredDist, stability, gyroAvailable, gyroPermissionRequested]);

    // Multiple faces lock state
    const [multiFaceLock, setMultiFaceLock] = useState(false);

    // Update multiFaceLock: Pi path uses attentionReason; browser path uses ref
    useEffect(() => {
        if (piMode) {
            const isMultiFace = piAttentionReason === "multiple_faces";
            setMultiFaceLock(isMultiFace);
            if (isMultiFace && !multiFaceFlaggedRef.current) {
                multiFaceFlaggedRef.current = true;
                cheatingFlagsRef.current.push({ type: "multiple_faces", timestamp: Date.now() });
            } else if (!isMultiFace) {
                multiFaceFlaggedRef.current = false;
            }
            return;
        }
        // Browser path
        const interval = setInterval(() => {
            setMultiFaceLock(multiFaceFlaggedRef.current);
        }, 100);
        return () => clearInterval(interval);
    }, [piMode, piAttentionReason]);

    return (
        <div className="relative min-h-screen flex flex-col" tabIndex={0}>
            {/* Attention overlay — face genuinely absent (Pi mode only).
                Only triggers for no_face. camera_starting / detection_error
                never block the test. multiple_faces has its own overlay below. */}
            {piMode && piAttentionReason === "no_face" && (
                <div className="absolute inset-0 z-50" style={{ backdropFilter: 'blur(20px)', WebkitBackdropFilter: 'blur(20px)', background: 'rgba(0,0,0,0.4)' }}>
                    <div className="flex flex-col items-center justify-center h-full">
                        <div className="glass rounded-3xl px-10 py-10 text-center max-w-xs w-full">
                            <h3 className="text-xl font-bold text-text-primary mb-2">No Face Detected</h3>
                            <p className="text-lg text-primary font-mono font-bold mb-2">Test Paused</p>
                            <p className="text-xs text-text-secondary">Please look at the screen to continue.</p>
                        </div>
                    </div>
                </div>
            )}
            {/* Multiple faces lock overlay */}
            {multiFaceLock && (
                <div className="absolute inset-0 z-50" style={{ backdropFilter: 'blur(20px)', WebkitBackdropFilter: 'blur(20px)', background: 'rgba(0,0,0,0.3)' }}>
                    <div className="flex flex-col items-center justify-center h-full">
                        <div className="glass rounded-3xl px-10 py-10 text-center max-w-xs w-full">
                            <h3 className="text-xl font-bold text-danger mb-2">Multiple Faces Detected</h3>
                            <p className="text-lg text-danger font-mono font-bold mb-2">Test Locked</p>
                            <p className="text-xs text-text-secondary">Only one person should be in front of the camera to continue.</p>
                        </div>
                    </div>
                </div>
            )}
            {/* Movement lock/blur overlay */}
            {movementLocked && (
                <div className="absolute inset-0 z-50" style={{ backdropFilter: 'blur(20px)', WebkitBackdropFilter: 'blur(20px)', background: 'rgba(0,0,0,0.3)' }}>
                    <div className="flex flex-col items-center justify-center h-full">
                        <div className="glass rounded-3xl px-10 py-10 text-center max-w-xs w-full">
                            <h3 className="text-xl font-bold text-text-primary mb-2">Please Hold Still</h3>
                            <p className="text-lg text-primary font-mono font-bold mb-2">Movement detected</p>
                            <p className="text-xs text-text-secondary">Return to your original position to continue</p>
                        </div>
                    </div>
                </div>
            )}
            {/* Gyro permission button for mobile */}
            {isMobile && !gyroPermissionRequested && (
                <div style={{ position: 'absolute', top: 10, left: 10, zIndex: 1000 }}>
                    <button style={{ padding: '10px', borderRadius: '8px', background: '#222', color: '#fff', fontSize: '16px' }} onClick={requestGyroPermission}>
                        Enable Gyroscope
                    </button>
                </div>
            )}
            {/* Gyro debug overlay */}
            {gyroAvailable && (
                <div style={{ position: 'absolute', top: 10, right: 10, zIndex: 1000, background: 'rgba(0,0,0,0.5)', color: '#0ff', padding: '8px', borderRadius: '8px', fontSize: '12px' }}>
                    <div>Gyro α: {lastGyroRef.current.alpha.toFixed(1)}</div>
                    <div>Gyro β: {lastGyroRef.current.beta.toFixed(1)}</div>
                    <div>Gyro γ: {lastGyroRef.current.gamma.toFixed(1)}</div>
                </div>
            )}
            {/* Top bar */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-white/5">
                <div className="flex items-center gap-4">
                    <span className="text-sm text-text-secondary font-medium">
                        {currentLevel?.snellen ?? "---"} · Line{" "}
                        {currentLevelIndex + 1} of {ACUITY_LEVELS.length}
                    </span>
                </div>
                <div className="flex items-center gap-4">
                    <span className="text-sm font-mono text-text-muted">
                        {stability === "UNLOCKED" && lockedDistance > 0
                            ? `d = ${lockedDistance.toFixed(2)}m`
                            : currentFilteredDist > 0
                                ? `d = ${currentFilteredDist.toFixed(2)}m`
                                : "d = ---"}
                    </span>
                    <span
                        className={`px-2 py-1 rounded-full text-xs font-medium ${stability === "UNLOCKED"
                            ? "bg-success/20 text-success"
                            : stability === "STABILIZING"
                                ? "bg-warning/20 text-warning"
                                : "bg-danger/20 text-danger"
                            }`}
                    >
                        {stability === "UNLOCKED"
                            ? "● Stable"
                            : stability === "STABILIZING"
                                ? `◐ ${stabilityTimer.toFixed(1)}s`
                                : "◯ Locked"}
                    </span>
                </div>
            </div>

            {/* Main test area */}
            <div className="flex-1 flex items-center justify-center relative">
                {/* Tumbling E */}
                <AnimatePresence mode="wait">
                    <motion.div
                        key={`${currentLevelIndex}-${currentTrialIndex}`}
                        initial={{ opacity: 0, scale: 0.8 }}
                        animate={{ opacity: 1, scale: 1 }}
                        exit={{ opacity: 0, scale: 0.8 }}
                        transition={{ duration: 0.2 }}
                        className="relative"
                    >
                        {/* Optotype rendered via SVG for pixel-perfect sizing */}
                        <svg
                            width={eHeightPx}
                            height={eHeightPx}
                            viewBox="0 0 5 5"
                            style={{
                                transform: `rotate(${eRotation}deg)`,
                                transition: "transform 0.2s ease",
                            }}
                        >
                            {optotypeType === "landolt-c" ? (
                                /* Landolt C: ring with gap facing RIGHT */
                                <path
                                    d="M 4.95 2 A 2.5 2.5 0 1 0 4.95 3 L 3.91 3 A 1.5 1.5 0 1 1 3.91 2 Z"
                                    fill="currentColor"
                                />
                            ) : (
                                /* Tumbling E facing RIGHT: 5×5 grid */
                                <>
                                    <rect x="0" y="0" width="5" height="1" fill="currentColor" />
                                    <rect x="0" y="0" width="1" height="5" fill="currentColor" />
                                    <rect x="0" y="2" width="5" height="1" fill="currentColor" />
                                    <rect x="0" y="4" width="5" height="1" fill="currentColor" />
                                </>
                            )}
                        </svg>
                    </motion.div>
                </AnimatePresence>

                {/* Feedback flash */}
                <AnimatePresence>
                    {showFeedback && (
                        <motion.div
                            className={`absolute inset-0 pointer-events-none ${showFeedback === "correct"
                                ? "bg-success/10"
                                : "bg-danger/10"
                                }`}
                            initial={{ opacity: 0 }}
                            animate={{ opacity: 1 }}
                            exit={{ opacity: 0 }}
                            transition={{ duration: 0.3 }}
                        />
                    )}
                </AnimatePresence>

                {/* STABILITY OVERLAY — blurs the chart until position is locked */}
                <AnimatePresence>
                    {stability !== "UNLOCKED" && (
                        <motion.div
                            className="absolute inset-0 flex flex-col items-center justify-center z-20"
                            style={{ backdropFilter: "blur(20px)", WebkitBackdropFilter: "blur(20px)" }}
                            initial={{ opacity: 0 }}
                            animate={{ opacity: 1 }}
                            exit={{ opacity: 0 }}
                            transition={{ duration: 0.5 }}
                        >
                            <div className="glass rounded-3xl px-10 py-10 flex flex-col items-center text-center max-w-xs w-full">
                                {stability === "LOCKED" ? (
                                    <>
                                        {/* Sonar-pulse rings */}
                                        <div className="relative w-24 h-24 mb-6 flex items-center justify-center">
                                            {[0, 1, 2].map((i) => (
                                                <motion.div
                                                    key={i}
                                                    className="absolute rounded-full border border-primary/30"
                                                    style={{ width: 20 + i * 20, height: 20 + i * 20 }}
                                                    animate={{ opacity: [0.7, 0.1, 0.7], scale: [0.85, 1.15, 0.85] }}
                                                    transition={{ duration: 2.5, delay: i * 0.6, repeat: Infinity, ease: "easeInOut" }}
                                                />
                                            ))}
                                            <div className="w-10 h-10 rounded-full bg-primary/15 border-2 border-primary/60 flex items-center justify-center z-10">
                                                <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
                                                    <circle cx="9" cy="9" r="3" stroke="#00D4AA" strokeWidth="1.5" fill="none" />
                                                    <line x1="9" y1="1" x2="9" y2="4.5" stroke="#00D4AA" strokeWidth="1.5" strokeLinecap="round" />
                                                    <line x1="9" y1="13.5" x2="9" y2="17" stroke="#00D4AA" strokeWidth="1.5" strokeLinecap="round" />
                                                    <line x1="1" y1="9" x2="4.5" y2="9" stroke="#00D4AA" strokeWidth="1.5" strokeLinecap="round" />
                                                    <line x1="13.5" y1="9" x2="17" y2="9" stroke="#00D4AA" strokeWidth="1.5" strokeLinecap="round" />
                                                </svg>
                                            </div>
                                        </div>
                                        <h3 className="text-xl font-bold text-text-primary mb-2">Position Yourself</h3>
                                        {currentFilteredDist > 0 ? (
                                            <p className="text-lg text-primary font-mono font-bold mb-2">
                                                {currentFilteredDist.toFixed(2)} m
                                            </p>
                                        ) : (
                                            <p className="text-sm text-text-muted mb-2 animate-pulse">Detecting face…</p>
                                        )}
                                        <p className="text-xs text-text-secondary leading-relaxed max-w-[180px]">
                                            Look at the camera and hold still for {STABILITY_LOCK_DURATION_S}s
                                        </p>
                                        {currentFilteredDist > 0 && currentFilteredDist < 1.5 && (
                                            <motion.p
                                                className="text-xs text-warning mt-3 font-medium"
                                                animate={{ opacity: [1, 0.5, 1] }}
                                                transition={{ duration: 1.5, repeat: Infinity }}
                                            >
                                                Move back a bit further
                                            </motion.p>
                                        )}
                                        {currentFilteredDist > 6 && (
                                            <motion.p
                                                className="text-xs text-warning mt-3 font-medium"
                                                animate={{ opacity: [1, 0.5, 1] }}
                                                transition={{ duration: 1.5, repeat: Infinity }}
                                            >
                                                Move a bit closer
                                            </motion.p>
                                        )}
                                    </>
                                ) : (
                                    <>
                                        {/* Countdown ring */}
                                        <div className="relative w-24 h-24 mb-5">
                                            <svg className="w-24 h-24 -rotate-90" viewBox="0 0 80 80">
                                                <circle cx="40" cy="40" r="34" strokeWidth="5" stroke="rgba(255,255,255,0.07)" fill="none" />
                                                <motion.circle
                                                    cx="40" cy="40" r="34"
                                                    strokeWidth="5"
                                                    stroke="#00D4AA"
                                                    fill="none"
                                                    strokeLinecap="round"
                                                    strokeDasharray={`${2 * Math.PI * 34}`}
                                                    strokeDashoffset={2 * Math.PI * 34 * (stabilityTimer / STABILITY_LOCK_DURATION_S)}
                                                    transition={{ duration: 0.15, ease: "linear" }}
                                                />
                                            </svg>
                                            <div className="absolute inset-0 flex flex-col items-center justify-center">
                                                <span className="text-3xl font-bold font-mono text-primary leading-none">
                                                    {Math.ceil(stabilityTimer)}
                                                </span>
                                                <span className="text-[9px] text-text-muted uppercase tracking-widest mt-0.5">sec</span>
                                            </div>
                                        </div>
                                        <h3 className="text-xl font-bold text-text-primary mb-1">Hold Still</h3>
                                        {currentFilteredDist > 0 && (
                                            <p className="text-base font-mono text-primary mb-2 font-semibold">
                                                {currentFilteredDist.toFixed(2)} m
                                            </p>
                                        )}
                                        <p className="text-xs text-text-muted">Locking your position…</p>
                                    </>
                                )}
                            </div>
                        </motion.div>
                    )}
                </AnimatePresence>
            </div>

            {/* Bottom bar — layout adapts for mobile vs desktop */}
            {isMobile ? (
                <div className="border-t border-white/5 px-4 pt-3 pb-8 flex flex-col items-center gap-3">
                    <div className="flex items-center justify-between w-full max-w-xs">
                        <div className="flex items-center gap-2">
                            {cameraActive && <div className="w-2 h-2 rounded-full bg-success animate-pulse" />}
                            <p className="text-xs text-text-muted">
                                Trial {currentTrialIndex + 1}/{currentLevel?.trialsPerLevel ?? 5}
                            </p>
                        </div>
                        <span className="text-xs text-text-muted">{currentLevel?.snellen ?? "---"}</span>
                    </div>
                    {/* Large touch D-pad */}
                    <div className="grid grid-cols-3 gap-2">
                        <div />
                        <button onClick={() => stability === "UNLOCKED" && (!piMode || piAttentionOk) && handleAnswer("up")} disabled={stability !== "UNLOCKED" || (piMode && !piAttentionOk)} className={`w-16 h-16 rounded-2xl flex items-center justify-center text-2xl transition-all ${stability === "UNLOCKED" && (!piMode || piAttentionOk) ? "bg-surface-light active:scale-90 active:bg-primary/20 cursor-pointer" : "bg-surface opacity-30 cursor-not-allowed"}`}>↑</button>
                        <div />
                        <button onClick={() => stability === "UNLOCKED" && (!piMode || piAttentionOk) && handleAnswer("left")} disabled={stability !== "UNLOCKED" || (piMode && !piAttentionOk)} className={`w-16 h-16 rounded-2xl flex items-center justify-center text-2xl transition-all ${stability === "UNLOCKED" && (!piMode || piAttentionOk) ? "bg-surface-light active:scale-90 active:bg-primary/20 cursor-pointer" : "bg-surface opacity-30 cursor-not-allowed"}`}>←</button>
                        <button onClick={() => stability === "UNLOCKED" && (!piMode || piAttentionOk) && handleAnswer("down")} disabled={stability !== "UNLOCKED" || (piMode && !piAttentionOk)} className={`w-16 h-16 rounded-2xl flex items-center justify-center text-2xl transition-all ${stability === "UNLOCKED" && (!piMode || piAttentionOk) ? "bg-surface-light active:scale-90 active:bg-primary/20 cursor-pointer" : "bg-surface opacity-30 cursor-not-allowed"}`}>↓</button>
                        <button onClick={() => stability === "UNLOCKED" && (!piMode || piAttentionOk) && handleAnswer("right")} disabled={stability !== "UNLOCKED" || (piMode && !piAttentionOk)} className={`w-16 h-16 rounded-2xl flex items-center justify-center text-2xl transition-all ${stability === "UNLOCKED" && (!piMode || piAttentionOk) ? "bg-surface-light active:scale-90 active:bg-primary/20 cursor-pointer" : "bg-surface opacity-30 cursor-not-allowed"}`}>→</button>
                    </div>
                    {/* Hidden camera elements — still used for face detection */}
                    <video ref={videoRef} className="hidden" playsInline muted />
                    <canvas ref={canvasRef} className="hidden" />
                </div>
            ) : (
                <div className="flex items-center justify-between px-6 py-4 border-t border-white/5">
                    {/* Mini camera feed */}
                    <div className="relative w-24 h-16 rounded-lg overflow-hidden bg-surface border border-white/5">
                        {piMode && piPreviewUrl ? (
                            <img
                                src={piPreviewUrl}
                                className="absolute inset-0 w-full h-full object-cover -scale-x-100"
                                alt="camera preview"
                            />
                        ) : (
                            <video
                                ref={videoRef}
                                className="absolute inset-0 w-full h-full object-cover -scale-x-100"
                                playsInline
                                muted
                            />
                        )}
                        <canvas ref={canvasRef} className="hidden" />
                        {cameraActive && (
                            <div className="absolute top-1 left-1">
                                <div className="w-2 h-2 rounded-full bg-success animate-pulse" />
                            </div>
                        )}
                    </div>
                    {/* Trial info */}
                    <div className="text-center">
                        <p className="text-xs text-text-muted mb-1">
                            Trial {currentTrialIndex + 1} / {currentLevel?.trialsPerLevel ?? 5}
                        </p>
                        <p className="text-xs text-text-secondary">Press ↑ ↓ ← → to answer</p>
                    </div>
                    {/* Direction buttons (touch fallback) */}
                    <div className="grid grid-cols-3 gap-1">
                        <div />
                        <button onClick={() => stability === "UNLOCKED" && (!piMode || piAttentionOk) && handleAnswer("up")} className="w-10 h-10 rounded-lg bg-surface-light hover:bg-primary/20 flex items-center justify-center text-lg transition-colors cursor-pointer" disabled={stability !== "UNLOCKED" || (piMode && !piAttentionOk)}>↑</button>
                        <div />
                        <button onClick={() => stability === "UNLOCKED" && (!piMode || piAttentionOk) && handleAnswer("left")} className="w-10 h-10 rounded-lg bg-surface-light hover:bg-primary/20 flex items-center justify-center text-lg transition-colors cursor-pointer" disabled={stability !== "UNLOCKED" || (piMode && !piAttentionOk)}>←</button>
                        <button onClick={() => stability === "UNLOCKED" && (!piMode || piAttentionOk) && handleAnswer("down")} className="w-10 h-10 rounded-lg bg-surface-light hover:bg-primary/20 flex items-center justify-center text-lg transition-colors cursor-pointer" disabled={stability !== "UNLOCKED" || (piMode && !piAttentionOk)}>↓</button>
                        <button onClick={() => stability === "UNLOCKED" && (!piMode || piAttentionOk) && handleAnswer("right")} className="w-10 h-10 rounded-lg bg-surface-light hover:bg-primary/20 flex items-center justify-center text-lg transition-colors cursor-pointer" disabled={stability !== "UNLOCKED" || (piMode && !piAttentionOk)}>→</button>
                    </div>
                </div>
            )}
        </div>
    );
}
