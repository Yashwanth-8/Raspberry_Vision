# NadiVision Attention & Distance Overhaul — Implementation Plan

## Current State

Confirmed by code review against the live codebase:

- **Face detection only:** `face_detection.py` runs YuNet (OpenCV DNN, ONNX, 320×240 fixed canvas) and decides `attention_ok` purely from face count (`no_face` / `multiple_faces` / single). YuNet's 5 landmarks (eye centres, nose, mouth corners) have no eyelid contour points — eye-openness cannot be derived from them directly. `face_detection.py`'s `process()` method does not even extract the raw landmark coordinates from the detection array; it only reads face count.

- **Distance:** `ultrasonic.py` reads HC-SR04 via `gpiozero` at ~17 Hz, filtered through Median(3)+EMA(α=0.7). `distance.py` (MediaPipe iris/IPD/face-width pinhole estimators) is dead Python code — it has zero callers in `main.py` and no role in any live execution path. It is not a browser fallback; the browser fallback runs entirely in the browser as TypeScript/MediaPipe. `distance.py` has never been imported in Pi mode production.

- **Camera/sensor split is already clean:** `main.py` hardcodes `iris_px: null` and `focal_length_px: null` in every WS payload. The frontend guards the entire MediaPipe distance path behind `if (!piMode)`. There is no crossing between the two paths and no open verification task required.

- **`SENSOR_TO_EYE_OFFSET_M` is undefined:** referenced in docs/roadmap but absent from `constants.py`. The offset is never applied; the distance broadcast carries raw sensor distance with no correction.

- **Known bugs:**
  - `main.py` `finally` block calls `detector.close()` unconditionally even when `detector = None`, causing an `AttributeError` that masks the original failure on any startup where YuNet fails to load.
  - `attention_ok` is force-set to `True` on `camera_starting`, `detector_unavailable`, and `detection_error` — three code paths where attention state is actively unknown but reported as confirmed.
  - `hardware-ws.ts` uses `attention_ok ?? true` — any malformed frame silently passes as "attention ok."
  - The stability FSM in `TestScreen.tsx` does not check `piAttentionOk`: the 3-second stability countdown runs uninterrupted during face-absent events. A patient can look away, have the test pause, and have the countdown complete in their absence — the test reaches `UNLOCKED` without confirming a full 3 seconds of stable, attended presence.

- **No attention signals beyond face count exist today:** no iris tracking, no head-pose or gaze detection, no eye-closure detection.

- **No per-eye monitoring:** `eyeTested: "OD" | "OS" | "OU"` in `store.ts` is written into `TestResult` at finish time only. No attention rule reads it. There is no mechanism to detect whether the untested eye is open or covered during a monocular test.

---

## Before Planning

Treat the current state section above as a validated summary, not a substitute for reading code. Before writing any implementation, read: `backend/main.py`, `camera.py`, `face_detection.py`, `ultrasonic.py`, `constants.py`, `distance.py`, and frontend `hardware-ws.ts`, `CameraSetupScreen.tsx`, `TestScreen.tsx`, `optotype.ts`, `store.ts`. Verify any detail that seems inconsistent with the plan before proceeding.

**Pre-work (complete before any objective work touches `TestScreen.tsx` or any clinical data is collected):**

- Remove or quarantine the gyro debug overlay in `TestScreen.tsx` (~lines 785–793), which renders raw gyroscope angles (`α`, `β`, `γ`) on-screen whenever `gyroAvailable=true` on a mobile device. Guard it behind `process.env.NODE_ENV === 'development'` or delete it entirely. This is a development artifact that must not appear during real test sessions.

---

## Objectives

**Execution order: 3 → 4 → 1 → 2.**

Objective 3 is self-contained and ships first. Objective 4 (architecture design and spike) is a hard prerequisite for Objective 1 — implementation of attention signals cannot begin until the architecture and executor decision gate are settled. Objective 2 implements within the attention framework from Objectives 4 and 1.

---

### Objective 3 — Apply the sensor-to-eye offset and fix outstanding bugs

This is the first PR. It is fully self-contained, touches no new features, and has the largest immediate impact on measurement accuracy: an uncompensated 10–15 cm sensor-to-eye offset at a 60 cm test distance produces a ~17–25% angular subtense error — one to two full logMAR lines.

**Deliverables:**

- [x] Add `SENSOR_TO_EYE_OFFSET_M` to `constants.py`. Confirm the value against the physical rig. Document the measurement method and the residual uncertainty (no rigid chin rest means this is a first-order correction, not a precision guarantee).
- [x] Add a single `sensor_to_eye_distance(raw_m: float) -> float` helper that applies the offset before the WS payload is assembled. This is the one canonical application point; no other code path should apply the offset.
- [x] Fix `detector.close()` None-guard in `main.py` `finally` block: guard the call with `if detector is not None:`. This uncovers real YuNet load failures instead of masking them with an `AttributeError`.
- [x] Remove forced `attention_ok=True` on `camera_starting`, `detector_unavailable`, and `detection_error`. Replace with `attention_ok=False` plus an explicit `attention_reason` string. The frontend has loading-state UI for these conditions; integrity takes priority.
- [x] Fix `?? true` via **Option B**: add a backend unit test asserting that every code path in `main.py`'s camera loop includes `attention_ok` in the payload. Do **not** change `hardware-ws.ts` — the `?? true` frontend default is preserved to prevent transient WS reconnects from blocking the UI. The integrity guarantee lives at the source, enforced by the test.
- [x] Delete `distance.py`. If a reference copy is wanted, move it to `dev/archived/distance_reference.py` with a prominent header comment explaining it is dead code with no active callers. Leaving it in place will mislead future contributors into believing a Python camera-distance path is live.
- [x] **Add a Pi-mode distance-source assertion test.** Add a backend test (pytest) that constructs a WS frame payload from `main.py`'s camera loop in Pi mode and asserts: `iris_px is None`, `focal_length_px is None`, and `distance_m` is the sole distance field. This test must pass throughout all subsequent objectives. Its purpose is to catch any future change that accidentally re-enables camera-based distance — notably during Objective 1 when iris tracking is added. If this test ever fails, it means camera data has silently re-entered the distance path.

---

### Objective 4 — Design the attention-monitoring architecture for Pi 4

This is the design and spike phase. **Objective 1 cannot begin until the executor decision gate below is resolved.**

Adding eye-closure detection and head-pose estimation to the existing asyncio/`run_in_executor` loop materially increases per-frame CPU load on a Pi 4. A saturated default `ThreadPoolExecutor` will introduce jitter into the WS broadcast loop. The purpose of this objective is to measure first and decide second — not to assume.

**Deliverables:**

- [x] **Architecture design document.** For each new attention signal (eye-closure, head-pose/gaze), specify:
  - Feature source (model type and size, or classical computation on existing landmarks)
  - Input resolution and per-frame cadence (every frame vs. decimated)
  - Estimated per-frame latency and CPU contribution
  - Executor assignment (thread pool vs. process pool) and thread budget
  - Integration point in the existing `camera_loop`
  - → `dev/obj4-architecture-design.md`

- [ ] **Hardware spike on a real Pi 4.** Spike code is complete (`backend/attention/`, `backend/dev/spike_benchmark.py`). **Must be run on Pi 4 hardware.** Run: `python3 dev/spike_benchmark.py --duration 60 --output spike_results.json` from `backend/`. Record results in §7 of the architecture document.
  - Acceptance criterion [1]: P95 total ≤ 25 ms/frame at 320×240
  - Acceptance criterion [2]: CPU ≤ 60% single-core averaged 10 s
  - Acceptance criterion [3]: No measurable P95 WS broadcast latency degradation (live measurement required — see §7.4)

- [ ] **Executor decision gate (required output before Objective 1 starts).** Provisional analysis in §6 of the architecture document concludes **ThreadPoolExecutor is sufficient**, but this must be confirmed by the Pi 4 hardware spike. Fill in §8 of `dev/obj4-architecture-design.md` after running the benchmark.

  If `ProcessPoolExecutor` is required, that migration is completed as the tail deliverable of Objective 4. Objective 1 does not start until the executor is confirmed.

**Classical-first policy (clarified):** "Classical-first" means preferring classical signal-processing algorithms — EAR thresholds, `solvePnP` geometry, temporal smoothing filters — as the analysis layer, even when those algorithms are applied to features derived from a model. It does not mean "no models." There is no classical path to per-eye eyelid state at 320×240 without a model; a lightweight model (e.g., int8 TFLite eye-openness classifier) is an acceptable feature extractor. What is precluded is adopting any model without first passing the measured spike above.

---

### Objective 1 — Add real attention signals

Implement within the architecture and executor framework produced by Objective 4. Camera is for face/eye/attention signals only; distance remains exclusively from the HC-SR04 in Pi mode. **This boundary is absolute and must be enforced by code, not convention** — past experience has shown that adding iris tracking can silently re-enable camera-based distance estimation if the WS payload assembly is not guarded.

**Deliverables:**

- [x] **Iris tracking.** Detect and track eye-centre positions frame-to-frame. Contribute to the unified attention signal.
  - **Hard prohibition:** iris pixel measurements (`iris_px`, `focal_length_px`, IPD estimates) produced by this work must NEVER be passed to any distance calculation. They are inputs to the attention pipeline only.
  - `iris_px` and `focal_length_px` in the WS payload must remain hardcoded `null` in Pi mode regardless of what data is available from the camera. Do not change these fields to propagate real values — doing so would silently enable camera-based distance on the frontend.
  - The backend assertion added in Objective 3 (see below) must remain green after this deliverable ships. If it fails, the implementation has violated the camera/sensor boundary.

- [x] **Head-pose detection.** Use `cv2.solvePnP` with the 5 YuNet landmarks to estimate yaw and pitch. If 5-point pose proves too noisy in development (landmark density insufficient for stable geometry), escalate to the additional landmark source selected in Objective 4's design document. Produce a boolean "looking away" signal with a defined angular threshold.

- [x] **Eye-closure detection.** Using the model and approach selected during the Objective 4 spike, produce a per-eye open/closed signal at the cadence and resolution determined in Objective 4. `MockEyeClosureDetector` active as placeholder; replace with `TFLiteEyeClosureDetector` once the model is selected and Pi 4 latency confirmed.

- [x] **Unified `attention_ok` signal.** Combine face-count, head-pose, and eye-closure into a single `attention_ok: bool` with a structured `attention_reason` string. `attention_ok` must be `False` on any face-absent, looking-away, or both-eyes-closed event. No code path may emit `attention_ok: True` when state is unknown.

- [x] **Deliverable 1.X — Attention-Stability Gate Coupling.**
  - In `TestScreen.tsx`: when `piAttentionOk` transitions to `false` during an active stability countdown, immediately transition the FSM to `LOCKED` and reset the countdown timer to zero.
  - When the next `piAttentionOk: true` frame arrives, the countdown restarts from zero — it does not resume from a paused value.
  - **Acceptance criterion:** the countdown does not advance past 0 s when a `piAttentionOk: false` frame arrives mid-countdown; the countdown restarts from zero on the next `piAttentionOk: true` frame.
  - **Test obligation:** shipped with 12 unit tests in `frontend/src/lib/__tests__/stability-fsm.test.ts` covering the FSM transition (`COUNTING → piAttentionOk: false → LOCKED`, countdown reset to zero) plus priority ordering and all boundary conditions. All 12 pass.

---

### Objective 2 — Untested eye detection for the single-eye test

Implement within the attention architecture from Objectives 4 and 1.

**Background:** During a monocular test (`eyeTested: "OD"` or `"OS"`), the system must actively monitor whether the untested eye appears clearly open. At 320×240 kiosk distance, the system cannot reliably distinguish a hand or patch covering the eye from a closed eyelid — both occlude the eye region equally. The goal is not to verify occlusion; it is to **detect when the untested eye appears clearly open** and respond. If confidence is low (poor lighting, occlusion too close to the lens), the response is pause-and-flag, not automatic invalidation. Persistent confirmed open detection triggers trial invalidation.

**Deliverables:**

- [x] **WebSocket protocol addition — `set_test_mode`.** Frontend sends `{"type": "set_test_mode", "eye": "OD" | "OS" | "OU"}` after the test eye is confirmed (after IPD screen, before `CameraSetupScreen` completes). The `handle_client` coroutine in `main.py` receives and stores this value. Backend defaults to `"OU"` on startup and on every WS reconnect — binocular mode, per-eye gate inactive. The per-eye detection rules below activate only when `eye` is `"OD"` or `"OS"`.

- [x] **Per-eye open detection.** Using the eye-closure signal from Objective 1, monitor the non-tested eye. Threshold: "untested eye appears clearly open" = eye-openness score > 0.65 for 10 consecutive frames (~333 ms at 30 fps). `UntestedEyeMonitor` in `backend/attention/untested_eye.py`.

- [x] **Response policy:**
  - Confirmed open detection: pause the test, emit `piAttentionOk: false`, display a clear patient-facing prompt (“Please cover your [left / right] eye”).
  - Low-confidence or ambiguous detection: flag the trial in the result record (`occlusion_confidence_low: true`) but do not pause.
  - Persistent confirmed open detection (> 2 s): `persistent_open: true` flag in WS frame — T to be calibrated on physical rig.

- [x] **Result payload additions.** Added `untestedEyeOpenEvents?: number` and `occlusionConfidenceLow?: boolean` to `TestResult` in `types.ts`; populated from live WS state in `finishTest()`.

- [ ] **Acceptance criterion:** in a bench test with the untested eye clearly open, the system pauses the test within 2 seconds of sustained detection; with the untested eye covered (hand, patch, or closed lid), the system does not pause. **Requires Pi 4 hardware with real TFLiteEyeClosureDetector.**

---

## Constraints

- **Target hardware:** Raspberry Pi 4 (4 GB). Pi 5 is a future option, not a dependency for this plan.
- **No rigid chin/forehead rest:** `SENSOR_TO_EYE_OFFSET_M` is a first-order correction with a documented residual uncertainty. Do not claim sub-centimetre accuracy. The offset measurement method and uncertainty budget must be stated alongside the constant.
- **Decoupled pipelines:** the attention/eye pipeline must never introduce latency into the distance broadcast loop. Both loops run independently. The attention loop runs on its own cadence and executor, as determined in Objective 4, with no shared blocking resource.
- **Ultrasonic is the sole distance source in Pi mode — no exceptions.** Distance broadcast in Pi mode must originate exclusively from `ultrasonic.py` via `sensor_to_eye_distance()`. Iris pixel size, IPD estimates, and any other camera-derived measurements must not enter the distance calculation under any circumstances. This applies even when iris tracking (Objective 1) makes those measurements available. The Pi-mode distance-source assertion test added in Objective 3 is the enforcement mechanism for this constraint — it must remain green across all PRs.
- **Classical-first, spike-gated ML:** classical signal-processing algorithms are the default analysis layer and may operate on model-derived features. Any new model addition requires passing the Objective 4 spike acceptance criteria (≤25 ms total inference, ≤60% CPU single-core averaged 10 s, no P95 degradation in distance broadcast) before production use.
- **Honest positioning:** this is a screening/pre-clinical device. Do not describe outputs as "clinical-grade" until validation data supports that claim.
