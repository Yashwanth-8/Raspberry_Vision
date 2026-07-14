# Nadi Vision (Hardware Edition) — Product Improvement Plan

> **Device:** Raspberry Pi 4 (4 GB RAM), Pi Camera Module 2/3, HC-SR04 ultrasonic sensor
> **Goal:** Clinical-grade, self-administered visual-acuity screening that stays lag-free on-device.
> **Scope of this plan:** (1) real-time gaze/attention monitoring architecture, (2) correct distance auto-scaling from the ultrasonic sensor shown in the preview, (3) product-developer improvements across performance, clinical robustness, and code health.

---

## 1. Current State (as-built, verified from code)

**Backend (`backend/`, Python, asyncio WebSocket on :8765)**
- `camera.py` — picamera2 720p `XRGB8888` main stream; a 320×240 BGR detection frame is produced by `cv2.resize` in the capture thread. OpenCV `VideoCapture` fallback for laptops.
- `face_detection.py` — `cv2.FaceDetectorYN` (YuNet 2023mar, ~80 KB) at a fixed 320×240 canvas. **Only** decides `attention_ok` from face count: `no_face → False`, `multiple_faces → False`, `single face → True`. Centring/gaze checks were explicitly removed as unreliable at 320×240. YuNet's 5 landmarks (eyes, nose, mouth corners) are **not** used.
- `ultrasonic.py` — HC-SR04 via `gpiozero` in a ~17 Hz background thread; 5-sample median pre-filter + 1-D Kalman. `confidence = 1.0` only when a valid reading arrived in the last 3 s, else `distance = 0.0`.
- `distance.py` — MediaPipe iris/IPD/face-width pinhole estimators. **Dead code** in Pi mode (distance now comes from the sensor); still imported/mirrored on the frontend browser path.
- `main.py` — 30 fps target loop: grab detect frame → YuNet in executor → read sensor → broadcast JSON every frame; JPEG preview (720p → 640×360, quality 65) every 3rd frame (~10 fps). `iris_px` / `focal_length_px` always `null`.

**Frontend (`frontend/`, Next.js kiosk + browser fallback)**
- `hardware-ws.ts` — singleton WS client; on connect sets `piMode`; pushes `distance/confidence` to Zustand; handles binary JPEG → object URL preview.
- `CameraSetupScreen.tsx` / `TestScreen.tsx` — dual path: Pi mode (sensor + YuNet) vs browser mode (MediaPipe FaceMesh). Distance overlay, stability FSM (LOCKED → STABILIZING → UNLOCKED), attention overlays (no_face / multiple_faces), movement lock via gyro (mobile).
- `optotype.ts` — `E height mm = d · tan(arcMinPerStroke · 5 · π/(180·60))`, then `mm → px` via `mmPerPx` from `screen-calibration.ts` (CSS resolution media query → devicePixelRatio heuristics → 96 PPI fallback).
- Auto-scaling: during LOCKED/STABILIZING the E sizes to live `currentFilteredDist`; during UNLOCKED it locks to `lockedDistance`.

**Known gaps found in code (not just docs)**
- `SENSOR_TO_EYE_OFFSET_M` is referenced in the README/roadmap but **is not defined in `constants.py` nor applied anywhere** — the ultrasonic measures sensor→torso/face, but optotype scaling and the preview both use raw sensor distance as if it were eye→screen distance.
- README is internally inconsistent (says MediaPipe in the architecture summary, YuNet elsewhere; lists `distance.py` under both stacks).
- "Attention monitoring" is really only "face presence" — no gaze/eye-region signal, so a user staring away (eyes closed / looking off-screen) with a detected face still counts as attentive.

---

## 2. Decision: Attention/Gaze Monitoring Architecture

**Recommendation: Keep OpenCV YuNet as the detector; do NOT fine-tune a custom model now. Add a lightweight eye-region/gaze heuristic layer on top of YuNet's existing 5 landmarks, with temporal smoothing.**

Rationale (product + engineering):
- YuNet already runs at ~8 ms/frame on Pi 4, is 80 KB, needs zero training data, and returns 5 landmarks (both eyes, nose, mouth corners) that are currently discarded.
- Fine-tuning a bespoke eye-region model requires a labelled dataset, an on-device inference runtime (tflite/ONNX), ongoing MLOps, and clinical re-validation — high cost, high risk, unclear accuracy gain for a *pause/resume attention gate* (not diagnostic).
- A "attention gate" only needs: face present, single person, head roughly facing screen, eyes open. That can be approximated from YuNet landmarks + bbox geometry + a cheap eye-openness proxy, all on the 320×240 canvas or a cropped eye ROI at higher res.

Proposed attention signal (all on-device, additive to current logic):
1. **Head-pose proxy** — from YuNet's eye/nose landmark asymmetry relative to the bbox, flag "looking away" when yaw/pitch proxy exceeds a threshold for > N consecutive frames.
2. **Eye-region ROI** — crop the eye region from the *full-res* frame (not the 320×240) around the eye landmarks; run a cheap open/closed proxy (e.g. eye-asp(aspect)-ratio via a tiny classical CV step, or a small optional tflite eye-state model behind a feature flag).
3. **Temporal debounce** — require the signal to persist ~300–500 ms before flipping `attention_ok`, to avoid flicker pausing the test.
4. **New `attention_reason` values** — `looking_away`, `eyes_closed`, in addition to existing `no_face` / `multiple_faces`.

Fallback path (only if heuristic proves insufficient in validation): fine-tune / integrate a lightweight eye-state model (e.g. a small MobileNet-based blink/gaze tflite) behind the existing `detector` abstraction so `main.py` and the WS contract don't change. Keep it a feature flag, quantized (int8), running only on the cropped eye ROI to stay within the Pi 4 latency budget.

**Explicitly deferred:** true gaze-vector estimation / calibrated eye tracking — out of scope for a screening pause gate.

---

## 3. Decision: Distance Auto-Scaling from the Sensor + Preview

**Problem:** the ultrasonic distance is treated as eye→screen distance for both optotype scaling and the on-screen readout, but it actually measures sensor→subject; there is no eye offset and no clear "measured by sensor" indication in the preview.

Proposed changes:
1. **Add `SENSOR_TO_EYE_OFFSET_M` to `constants.py`** and apply it in `ultrasonic.py` (or a single conversion point in `main.py`) so the broadcast `distance` is the corrected eye→screen distance. Document the sign convention and the physical-enclosure calibration step.
2. **Preview overlay from sensor** — render the corrected distance prominently on the Pi preview in `CameraSetupScreen` and the `TestScreen` mini-preview, clearly labelled as ultrasonic-derived, with the confidence/validity state (green = sensor active, amber = stale/out-of-range).
3. **Out-of-range UX** — when `confidence = 0` (sensor unplugged / target < 4 cm or > 3.5 m), show a "move into range" prompt instead of a silent `0.00 m`, and keep the test correctly blocked.
4. **Range-band guidance** — the optimal-distance band (currently `2–5 m` desktop / `0.5–1.5 m` mobile) should be reconciled with the HC-SR04 reliable range (`0.04–3.5 m`) so the guidance never asks the user to stand where the sensor cannot measure.
5. **Optotype scaling continuity** — ensure the E resizes smoothly from the corrected live distance during positioning and locks cleanly; verify the mmPerPx screen calibration is trustworthy on the actual kiosk HDMI panel (add a one-time physical calibration check for the fixed enclosure).

---

## 4. Performance & Efficiency (Pi 4, lag-free alongside distance loop)

1. **Decouple detection cadence from broadcast cadence** — run YuNet at ~10–15 fps but broadcast distance at 30 fps; distance is the latency-sensitive signal and is already cheap.
2. **Avoid redundant `setInputSize`/resize** — confirm the detect frame is produced once in `camera.py` and never re-resized in `face_detection.py`.
3. **Executor/thread hygiene** — validate the asyncio `run_in_executor` default threadpool isn't starved; consider a dedicated single-thread executor for YuNet.
4. **Preview bandwidth** — keep JPEG at ~10 fps / quality 65 (already good); make it adaptive if multiple clients connect.
5. **Thermal** — surface CPU temperature/throttle state; document heatsink/fan requirement (README already hints at 80 °C throttling).

---

## 5. Product & Clinical Robustness

1. **Attention → pause/resume UX** — clear, calm overlays for each `attention_reason`; auto-resume with a short re-stabilise so results aren't corrupted by the pause.
2. **Integrity flags** — extend existing cheat flags (fast answer, face lost, multiple faces, tab/fullscreen exit) with `looking_away` / `eyes_closed` durations in the results report.
3. **Sensor↔camera agreement check** — optional sanity cross-check: if the camera sees a face but the sensor reads no target (or vice-versa), flag a positioning/hardware issue.
4. **Calibration workflow for the fixed enclosure** — once mounted, calibrate `SENSOR_TO_EYE_OFFSET_M` and screen `mmPerPx` and persist them.
5. **Offline-first** — YuNet model is downloaded at setup; ensure the device works with no internet at test time (verify no CDN dependency remains on the Pi path; MediaPipe CDN is browser-fallback only).

---

## 6. Code Health / Tech Debt

1. **Remove or quarantine dead code** — `distance.py` (Pi path), unused `iris_px`/`focal_length_px` fields, legacy `calibrate`/`set_focal_length` WS messages — either delete or clearly mark as browser-fallback-only.
2. **Single source of truth for constants** — `constants.py` (backend) and `constants.ts` (frontend) duplicate acuity levels/thresholds; document the sync requirement or generate one from the other.
3. **README accuracy** — fix MediaPipe-vs-YuNet inconsistencies, correct the `distance.py`/`face_detection.py` descriptions, and document the new attention signals and offset calibration.
4. **Detector abstraction** — formalise a `Detector` interface so YuNet vs a future tflite eye model are swappable without touching `main.py`.
5. **Tests** — add unit tests for the offset conversion, the attention debounce state machine, and the optotype sizing math.

---

## 7. Proposed Sequencing (product view)

- **Phase 1 (correctness, low risk):** sensor→eye offset + preview distance display + out-of-range UX + range-band reconciliation + README fix. (Directly satisfies the "auto scaling from sensor shown properly" ask.)
- **Phase 2 (attention gate on YuNet):** head-pose + eye-openness heuristic behind the existing detector, new `attention_reason`s, temporal debounce, pause/resume UX. (Satisfies "eye-region focused attention" without a new model.)
- **Phase 3 (optional model):** only if Phase 2 validation is insufficient — quantized tflite eye-state model behind the feature flag; clinical re-validation.
- **Phase 4 (hardening):** dead-code removal, detector abstraction, tests, thermal/perf telemetry.

---

## 8. Open Questions

- Is the enclosure geometry (sensor-to-screen, sensor-to-eye) fixed yet, so the offset can be a constant, or must it be measured per-session?
- Target minimum test distance on the kiosk — does it stay within HC-SR04's 3.5 m reliable range, or is a ToF sensor (per `Objectives.md`) the real path?
- Is Pi 5 in scope, which would relax the latency budget for an on-device eye model?
