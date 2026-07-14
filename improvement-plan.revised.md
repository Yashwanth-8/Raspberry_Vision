# Nadi Vision (Hardware Edition) — Product Improvement Plan (Revised)

> **Device:** Raspberry Pi 4 (4 GB RAM), Pi Camera Module 2/3, HC-SR04 ultrasonic sensor
> **Goal:** Self-administered visual-acuity **screening** that stays lag-free on-device.
> **Positioning:** "screening / pre-clinical prototype" — NOT "clinical-grade" — until the error budget in §4 is met with validation data. Two of three accuracy pillars (screen `mmPerPx`, sensor→eye distance) are currently unsound.
> **Scope:** (1) real-time eye-region attention monitoring, (2) correct distance auto-scaling from the ultrasonic sensor shown properly in the preview, (3) product-developer improvements across performance, clinical robustness, and code health.
>
> _Revised after a two-model review loop (product owner: Opus 4.8; developer: Codex 5.3), 2 iterations, early-exit on consensus. Full transcripts in `/tmp/improvement-plan.md/`._

---

## 0. Adopted Default Assumptions (user-overridable)

These were unanswered clarifications; the plan adopts explicit defaults so it is actionable. **Confirm or override.**

- **A1 — Test distance:** bounded kiosk workflow at a **fixed 2.0–3.0 m**, explicitly NOT the 6 m equivalence in `Objectives.md`. 2–3 m sits inside HC-SR04's reliable band (`_MAX_M = 3.50` in `ultrasonic.py`) and renders 20/20 (~4.4 mm E at 3 m) and 20/16 (~3.5 mm) fine. 6 m + ToF is a separate later milestone.
- **A2 — Enclosure:** **no rigid chin/forehead rest** in this revision. `SENSOR_TO_EYE_OFFSET_M` is therefore an approximate first-order correction with a **residual error budget**, plus a soft on-screen eye-alignment guide. If a rigid rest is later added, the offset can be promoted to a validated constant.
- **A3 — Detector-outage policy:** **proceed but degrade loudly** — non-dismissible "Attention monitoring unavailable" banner + mandatory integrity flag; operator acknowledgment required in attended/kiosk mode; hard-block only in unattended self-test mode.

---

## 1. Current State (as-built, verified from code)

**Backend (`backend/`, asyncio WebSocket :8765)**
- `camera.py` — picamera2 720p `XRGB8888`; 320×240 BGR detection frame produced by `cv2.resize` in the capture thread. OpenCV `VideoCapture` fallback for laptops.
- `face_detection.py` — `cv2.FaceDetectorYN` (YuNet 2023mar ONNX via OpenCV DNN, ~80 KB) at fixed 320×240. Decides `attention_ok` from **face count only** (`no_face`/`multiple_faces` → False, single → True). YuNet returns exactly **5 landmarks** (two eye *centres*, nose, two mouth corners — **no eyelid points**), all currently unused (only `f[14]` score is read). Centring/gaze checks were removed as unreliable at 320×240 (±3–5 px).
- `ultrasonic.py` — HC-SR04 via `gpiozero`, ~17 Hz thread; 5-sample median + 1-D Kalman; `confidence = 1.0` only if a valid reading arrived within 3 s, else `distance = 0.0`. Reliable range 0.04–3.5 m.
- `distance.py` — MediaPipe iris/IPD/face-width pinhole estimators; **dead code on the Pi path** (never imported by `main.py`), still mirrored on the browser fallback.
- `main.py` — 30 fps loop: grab detect frame → YuNet in executor → read sensor → broadcast JSON; JPEG preview (720p→640×360, quality 65) every 3rd frame. Forces `attention_ok=True` on `camera_starting`/`detector_unavailable`/`detection_error` (silent integrity gap). `iris_px`/`focal_length_px` always null.

**Frontend (`frontend/`)**
- `hardware-ws.ts` — singleton WS client; sets `piMode`, pushes `distance/confidence` to Zustand; binary JPEG → object URL preview. Uses permissive `?? true` defaults for attention fields.
- `CameraSetupScreen.tsx` / `TestScreen.tsx` — dual path (Pi sensor+YuNet vs browser MediaPipe). Stability FSM (LOCKED→STABILIZING→UNLOCKED), attention overlays, mobile gyro movement lock. Copy still says "Distance is measured automatically using face detection" even in Pi mode. Optimal-distance band shows 2–5 m / 6 m though sensor caps at 3.5 m.
- `optotype.ts` — `E height mm = d·tan(arcMinPerStroke·5·π/(180·60))`, then mm→px via `mmPerPx` from `screen-calibration.ts` (CSS media query → devicePixelRatio guesses → 96 PPI fallback; `TestScreen.tsx` hardcodes `0.25 mm/px` fallback).

**Confirmed defects (code, not just docs)**
- `SENSOR_TO_EYE_OFFSET_M` referenced in README/roadmap but **undefined in code and never applied**.
- README internally inconsistent (MediaPipe vs YuNet; `distance.py` placement) and falsely claims the camera "pauses when the patient looks away" (it does not).
- `main.py` shutdown `finally` calls `detector.close()` unconditionally though `detector` can be `None` → `AttributeError` masking the real failure.

---

## 2. Attention/Gaze Monitoring Architecture (decision)

**Decision: Keep OpenCV YuNet. Do NOT fine-tune a bespoke model as the primary bet.** For a pause/resume *gate* (not a diagnostic signal), a custom model adds a dataset, an on-device runtime, MLOps, and clinical re-validation for marginal benefit. True gaze-vector estimation is explicitly deferred.

**Corrected scope (a prior premise was wrong):**
- YuNet's 5 landmarks **cannot** yield an eye-aspect-ratio / openness measure (no eyelid points). Eye-openness requires a **separate ROI classifier/heuristic** — this is real added scope, not "a cheap classical step."
- Head-pose gating must **not** run on the 320×240 canvas (±3–5 px noise). If pursued, run on a **higher-res crop derived from the same captured frame**, with quantified error.

**Attention pipeline (additive, feature-flagged):**
1. Keep YuNet at 320×240 for the **face-count gate** (present / single / multiple).
2. Optional **eye-region ROI path**, cropped from the **same base frame** as detection (avoid the two-grab temporal mismatch): map 320×240 landmarks → full-res coords, crop the eye ROI once.
3. **Default = cheap appearance heuristic** (intensity/edge temporal consistency for open/closed + coarse look-away). This alone is expected to satisfy the acceptance criteria in §4.
4. **Optional int8 TFLite eye-state model on the ROI only** — strictly behind a **measured gate** (see §4); a conditional fallback, not a prerequisite.
5. **Temporal debounce** 300–500 ms before flipping `attention_ok`; new `attention_reason` values `eyes_closed` / `looking_away` added **only once validated**.
6. Run ROI inference on a **dedicated single-thread executor** with frame-skipping under load; keep it decoupled from the 30 fps broadcast so distance never lags.

---

## 3. Distance Auto-Scaling from the Sensor + Preview (decision)

**Problem:** ultrasonic distance is used as eye→screen distance for scaling and readout, with no offset and no clear "measured by sensor" indication.

**Changes (all sensor-agnostic mechanism unless noted):**
1. Add `SENSOR_TO_EYE_OFFSET_M` slot + a **single conversion helper** (`constants.py` + `main.py`) applied before the WS payload. Value ships **provisional/uncalibrated** until the §4 spike (HC-SR04-specific to commit the number).
2. **Preview overlay from the sensor** — render the corrected distance prominently on the Pi preview (`CameraSetupScreen` + `TestScreen` mini-preview), labelled as ultrasonic-derived, with a validity state (green = active, amber = stale/out-of-range).
3. **Out-of-range UX** — replace silent `0.00 m` with an explicit "Out of range / sensor inactive" prompt; keep the test correctly blocked.
4. **Single distance gate** — introduce `distance_valid` (boolean) as the **sole** progression authority; switch `TestScreen.tsx` from `distanceConfidence >= 0.5` to `distance_valid`. `confidence` becomes UX telemetry only (no dual gate).
5. **Range-band reconciliation** — align the UI optimal band with the A1 2–3 m target and the sensor's reliable range; never invite users where the sensor can't measure.
6. **Minimum-px-per-stroke floor** — at 2–3 m the smallest optotypes approach the panel pixel limit; auto-suppress/flag levels whose stroke falls below a readability floor on the calibrated panel (`optotype.ts`).
7. **WS contract additions** (fail-safe): `distance_source` ("ultrasonic"), `distance_valid`, `attention_monitoring_active`. In `hardware-ws.ts`, missing `distance_valid` → false, missing `attention_monitoring_active` → false; `attention_ok` permissive only when `attention_monitoring_active === true`.

---

## 4. Performance, Error Budget & Acceptance Criteria (Pi 4)

**Explicit error budget (Phase-1 success is testable, not vibe-checked):**
- Distance within **±2%** → optotype within **±2%** → acuity within **±0.02 logMAR**.
- Attention: **false-pause rate < 1/min** on attentive clips; sustained **eyes-closed >1 s caught ≥ 90%**; **pause/resume latency ≤ 500 ms**.

**Performance:**
1. **Decouple detection cadence from broadcast** — YuNet/ROI at ~10–15 fps; distance broadcast at 30 fps.
2. **Dedicated single-thread executor** for detection/ROI so the 30 fps loop is never starved; frame-skip under load.
3. **Benchmark harness on Pi 4** — stage timings (capture / YuNet / ROI / WS send); replace the unverified "~8 ms YuNet" docstring number with a measured figure before finalising cadence.
4. Preview stays ~10 fps / quality 65; make adaptive if multiple clients connect.
5. Surface CPU temperature / throttle state (README already flags 80 °C throttling).
6. **Drop the `setInputSize`/resize micro-optimisation** — negligible; `camera.py` already produces the detect frame once and `face_detection.process()` skips the resize when shapes match.

**TFLite go/no-go spike (before any model coding):** (1) `tflite-runtime` installs on ARM without shadowing apt numpy/opencv/picamera2 in the `--system-site-packages` venv; (2) ROI inference + YuNet loop within latency budget; (3) no 30 fps starvation. If any fails → ship the classical-heuristic-only attention path for this milestone.

---

## 5. Product & Clinical Robustness

1. **Attention pause/resume UX** — calm, per-`attention_reason` overlays; auto-resume with a short re-stabilise so a pause never corrupts results.
2. **Integrity report** — extend existing cheat flags with `looking_away`/`eyes_closed` durations AND an **`attention_monitoring_active`** flag (records when the gate was down) per A3.
3. **Screen `mmPerPx` calibration = provisioning-grade** (co-equal Phase-1 validity pillar): mandatory one-time **technician** physical calibration (known-size object) with a verification screen, persisted in **device-level config read at boot** (backend-owned) — NOT a per-session patient step and NOT `localStorage` (wiped on kiosk cache-clear/reflash). Gate "Start test" on valid calibration. Auto-detect stays a bootstrap suggestion only.
4. **Sensor↔camera agreement check** (optional) — flag positioning/hardware issues when camera sees a face but sensor reads no target (or vice-versa).
5. **Offline-first** — verify no CDN dependency on the Pi path at test time (MediaPipe CDN is browser-fallback only); YuNet downloaded at setup.

---

## 6. Code Health / Tech Debt

1. **Bug fix (fold immediately):** guard `main.py` shutdown `finally` with `if detector is not None: detector.close()`; audit other optional teardown calls.
2. **Dead-code quarantine** — `distance.py` (Pi path), unused `iris_px`/`focal_length_px`, legacy `calibrate`/`set_focal_length` WS messages: delete or clearly mark browser-fallback-only.
3. **Detector abstraction** — formalise a `Detector` interface (YuNet vs future TFLite eye model swappable without touching `main.py`); likewise a **backend sensor abstraction** so the frontend contract is stable across a ToF swap.
4. **Constants single-source** — document/sync the `constants.py` ↔ `constants.ts` duplication (acuity levels/thresholds).
5. **README accuracy** — fix MediaPipe-vs-YuNet inconsistencies, correct `distance.py`/`face_detection.py` descriptions, remove the false "pauses when patient looks away" claim, document the new attention signals, offset calibration, and A1–A3 assumptions.
6. **Tests** — offset conversion, attention debounce state machine, optotype sizing math (incl. the px-per-stroke floor), fail-safe WS defaults.

---

## 7. Sequencing (gate-vs-parallel RESOLVED via task-level split)

**Phase 1 — sensor-agnostic (IMPLEMENTED in current codebase):**
- WS contract additions + `hardware-ws.ts` fail-safe mapping + both screens' source labels. ✅
- Offset **plumbing** (constant slot + single conversion helper), value flagged provisional. ✅
- Out-of-range / sensor-inactive UX; switch progression gate to `distance_valid`. ✅
- Provisioning-ready calibration path using device config in frontend (`device-config.json` bootstrap). ✅
- `attention_monitoring_active` banner + integrity signaling path (A3 policy support). ✅
- README truthfulness fixes + `detector.close()` None-guard bug fix. ✅
- Remaining carry-over from Phase 1: backend sensor abstraction interface, dead-code quarantine, and benchmark-harness scaffold. ⏳

**HC-SR04 characterisation spike (parallel, 1–2 days):** tape-measure vs HC-SR04 at 1/2/3 m on a human torso/face.
- **Gate condition (decidable):** if error ≤ budget at the A1 distance → freeze the `SENSOR_TO_EYE_OFFSET_M` constant, publish the bounded range band, drop the provisional flag. Else → keep HC-SR04 interim-only, publish NO HC-SR04 accuracy claims, prioritise the ToF spike.

**Gated on the spike (HC-SR04-specific, at risk of rework):** committing the production offset number + single-constant validity claim; final range-band numbers + filter tuning in `ultrasonic.py`; any external HC-SR04 distance-accuracy claim.

**Phase 2 — attention gate on YuNet (NEXT PRIORITY):**

Implement these items in order:
1. Add a dedicated attention pipeline module that keeps current YuNet face-count gating and introduces a same-frame eye ROI path.
2. Implement classical heuristic eye-state/attention scoring first (default path) with 300–500 ms debounce.
3. Add new `attention_reason` values (`eyes_closed`, `looking_away`) only after threshold tuning.
4. Build replay-based evaluation scripts and enforce acceptance criteria from §4:
   - false pause < 1/min
   - eyes-closed > 1 s detected >= 90%
   - pause/resume latency <= 500 ms
5. Add optional int8 TFLite ROI model behind feature flag **only if** the install/runtime gate passes on Pi 4.
6. Keep ROI inference cadence decoupled from 30 fps distance broadcast (no distance-loop lag).

**Phase 3 — optional model:** only if Phase-2 validation is insufficient — quantized TFLite eye-state on ROI, clinical re-validation.

**Phase 4 — hardening:** detector/sensor abstractions finalised, tests, thermal/perf telemetry.

**Non-blocking open item:** exact scheduling of the ToF migration milestone relative to the HC-SR04 interim release.

---

## 8. Rough Effort (developer estimates)

- WS fail-safe contract (backend+frontend): 0.5–1 day
- Distance-gate reconciliation (`distance_valid`): 0.5 day
- Offset plumbing: ~0.5 day; out-of-range UX: ~0.5–1 day
- Provisioning-grade `mmPerPx` calibration: 1.5–2.5 days
- Attention-outage visibility (banner + flags): 0.5–1 day
- HC-SR04 spike: 1–2 days · TFLite go/no-go spike: 1–1.5 days
- Phase-2 ROI attention (heuristic path): 4–6 days
- `detector.close()` bug fix: <0.25 day
