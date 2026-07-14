/**
 * hardware-ws.ts
 *
 * WebSocket client that connects to the Python backend running on the
 * Raspberry Pi at ws://localhost:8765.
 *
 * When connected (Pi mode), distance + face data are pushed from the
 * Python backend (HC-SR04 ultrasonic + YuNet via Pi Camera) into the
 * Zustand store — replacing the browser-side MediaPipe pipeline entirely.
 *
 * Usage:
 *   const { piMode, faceDetected, attentionOk } = useHardwareWS();
 *
 * The hook is safe to call on any screen. On a normal laptop (no backend
 * running), piMode stays false and nothing changes.
 */

import { useEffect, useRef, useState } from "react";
import { useAppStore } from "@/lib/store";

const WS_URL = "ws://localhost:8765";
const RECONNECT_DELAY_MS = 2000;
const CONNECT_TIMEOUT_MS = 5000; // if no open within this time → not Pi mode

export interface HardwareWSState {
    /** true when connected to the Python backend (Pi mode) */
    piMode: boolean;
    faceDetected: boolean;
    faceCount: number;
    irisPx: number | null;
    focalLengthPx: number;
    /** Object URL of the latest JPEG preview frame from the Pi camera */
    previewUrl: string | null;
    /** true when all attention rules pass (single face present) */
    attentionOk: boolean;
    /** true only when backend detector is healthy */
    attentionMonitoringActive: boolean;
    /** "ok" | "no_face" | "multiple_faces" | "camera_starting" | "detection_error" */
    attentionReason: string;
    /** authoritative gate from backend for whether distance can drive the test */
    distanceValid: boolean;
    /** source of active distance signal (e.g. ultrasonic, tof) */
    distanceSource: string;
}

/**
 * Singleton WebSocket manager so multiple components share one connection.
 */
class HardwareWSManager {
    private static instance: HardwareWSManager | null = null;

    private ws: WebSocket | null = null;
    private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    private destroyed = false;

    // Subscribers get notified of state changes
    private subscribers: Set<(state: HardwareWSState) => void> = new Set();

    private state: HardwareWSState = {
        piMode: false,
        faceDetected: false,
        faceCount: 0,
        irisPx: null,
        focalLengthPx: 0,
        previewUrl: null,
        attentionOk: true,
        attentionMonitoringActive: false,
        attentionReason: "ok",
        distanceValid: false,
        distanceSource: "unknown",
    };

    static getInstance(): HardwareWSManager {
        if (!HardwareWSManager.instance) {
            HardwareWSManager.instance = new HardwareWSManager();
        }
        return HardwareWSManager.instance;
    }

    subscribe(cb: (state: HardwareWSState) => void): () => void {
        this.subscribers.add(cb);
        cb(this.state); // immediate snapshot
        return () => this.subscribers.delete(cb);
    }

    private notify() {
        for (const cb of this.subscribers) cb({ ...this.state });
    }

    connect() {
        if (this.destroyed || this.ws?.readyState === WebSocket.OPEN) return;

        // Cancel any pending reconnect
        if (this.reconnectTimer) clearTimeout(this.reconnectTimer);

        try {
            this.ws = new WebSocket(WS_URL);
        } catch {
            this.scheduleReconnect();
            return;
        }

        // If socket doesn't open within CONNECT_TIMEOUT_MS, treat as not Pi
        const connectTimeout = setTimeout(() => {
            if (this.ws && this.ws.readyState !== WebSocket.OPEN) {
                this.ws.close();
                // Don't reconnect — user is on a laptop
            }
        }, CONNECT_TIMEOUT_MS);

        this.ws.onopen = () => {
            clearTimeout(connectTimeout);
            this.state = { ...this.state, piMode: true };
            this.notify();
            console.log("[HardwareWS] Connected to Pi backend at", WS_URL);
        };

        this.ws.onmessage = (ev) => {
            // Binary message = JPEG preview frame from Pi camera
            if (ev.data instanceof Blob) {
                const url = URL.createObjectURL(ev.data);
                const old = this.state.previewUrl;
                this.state = { ...this.state, previewUrl: url };
                this.notify();
                // Defer revocation so React finishes rendering the new URL first
                if (old) setTimeout(() => URL.revokeObjectURL(old), 500);
                return;
            }
            try {
                const msg = JSON.parse(ev.data as string);
                if (msg.type !== "frame") return;

                // Always push distance + confidence to the store so the frontend
                // always reflects the true sensor state. When confidence=0 the
                // store gets distance=0, which stops the stability FSM in TestScreen.
                useAppStore.getState().setDistance(
                    msg.distance ?? 0,
                    msg.raw_distance ?? msg.distance ?? 0,
                    msg.confidence ?? 0,
                    msg.distance_valid ?? false,
                    msg.distance_source ?? "unknown",
                );

                // Update local state for consumers
                const monitoringActive = msg.attention_monitoring_active ?? false;
                this.state = {
                    ...this.state,
                    faceDetected: msg.face_detected ?? false,
                    faceCount: msg.face_count ?? 0,
                    irisPx: msg.iris_px ?? null,
                    focalLengthPx: msg.focal_length_px ?? 0,
                    attentionOk: monitoringActive ? (msg.attention_ok ?? true) : true,
                    attentionMonitoringActive: monitoringActive,
                    attentionReason: msg.attention_reason ?? "ok",
                    distanceValid: msg.distance_valid ?? false,
                    distanceSource: msg.distance_source ?? "unknown",
                };
                this.notify();
            } catch {
                // malformed message — ignore
            }
        };

        this.ws.onclose = () => {
            clearTimeout(connectTimeout);
            if (this.state.previewUrl) URL.revokeObjectURL(this.state.previewUrl);
            this.state = {
                ...this.state,
                piMode: false,
                faceDetected: false,
                faceCount: 0,
                previewUrl: null,
                attentionMonitoringActive: false,
                distanceValid: false,
                distanceSource: "unknown",
            };
            this.notify();
            if (!this.destroyed) this.scheduleReconnect();
        };

        this.ws.onerror = () => {
            // onclose fires after onerror — no extra handling needed
        };
    }

    private scheduleReconnect() {
        this.reconnectTimer = setTimeout(() => this.connect(), RECONNECT_DELAY_MS);
    }

    /**
     * Send the user's IPD to the Python backend so it can use it for
     * IPD-based distance estimation.
     */
    sendIPD(ipdMm: number) {
        if (this.ws?.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({ type: "calibrate", ipd_mm: ipdMm }));
        }
    }

    destroy() {
        this.destroyed = true;
        if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
        this.ws?.close();
        HardwareWSManager.instance = null;
    }
}

// ---------------------------------------------------------------------------
// React hook
// ---------------------------------------------------------------------------

export function useHardwareWS(): HardwareWSState {
    const manager = HardwareWSManager.getInstance();
    const [state, setState] = useState<HardwareWSState>(() => ({
        piMode: false,
        faceDetected: false,
        faceCount: 0,
        irisPx: null,
        focalLengthPx: 0,
        previewUrl: null,
        attentionOk: true,
        attentionMonitoringActive: false,
        attentionReason: "ok",
        distanceValid: false,
        distanceSource: "unknown",
    }));

    useEffect(() => {
        manager.connect();
        const unsub = manager.subscribe(setState);
        return unsub;
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    return state;
}

/**
 * Send IPD to the Python backend (call after IPDScreen confirms).
 */
export function sendIPDToBackend(ipdMm: number) {
    HardwareWSManager.getInstance().sendIPD(ipdMm);
}
