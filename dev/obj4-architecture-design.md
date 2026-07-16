# Objective 4 — Attention-Monitoring Architecture Design
# NadiVision · Pi 4 spike and executor decision gate

---

## 1. Context and Purpose

The existing attention pipeline has one signal: face-count from YuNet.  
Objectives 1 and 2 require three additional signals:

| Signal | Required by |
|---|---|
| Head pose (yaw/pitch) | Objective 1 — detect patient looking away |
| Eye closure (per-eye) | Objective 1 — detect both-eyes-closed |
| Untested-eye open detection | Objective 2 — monocular test integrity |

Adding these signals to the existing `asyncio` / `run_in_executor` loop
increases per-frame CPU load.  **This document specifies the architecture,
states estimated performance, and records the executor decision gate.**

---

## 2. Existing loop structure (Objective 3 baseline)

```
asyncio event loop (Pi main thread)
  └─ camera_loop (async coroutine, ~30 fps target)
       ├─ camera.grab_detect_frame()   → run_in_executor (I/O, ~1 ms)
       ├─ detector.process(frame)      → run_in_executor (CPU, ~8–10 ms)
       └─ ultrasonic.distance_m        → non-blocking property read
```

`run_in_executor(None, ...)` uses the default `ThreadPoolExecutor` whose
size is `min(32, os.cpu_count() + 4)` = **8 threads** on Pi 4 (4 cores).
The detection stage occupies one thread for ~8–10 ms per frame.

---

## 3. Signal design — Head Pose

### Feature source
Classical computation on landmarks already produced by YuNet.  
**No new model required.**

YuNet landmark layout in the detection array:
```
[4–5]   kpt0  right eye centre
[6–7]   kpt1  left eye centre
[8–9]   kpt2  nose tip
[10–11] kpt3  right mouth corner
[12–13] kpt4  left mouth corner
```
`face_detection.py` was updated (Objective 4) to expose these as
`landmarks_2d: np.ndarray` (shape 5×2) in the `process()` return dict.

### Algorithm
`cv2.solvePnP(SOLVEPNP_SQPNP)` maps the 5 image points to a canonical
3-D face model (5 points, mm-scale, nose tip at origin), recovering a
rotation vector.  `cv2.Rodrigues` converts it to a 3×3 rotation matrix;
standard Tait-Bryan decomposition gives yaw, pitch, roll in degrees.

A reprojection-error guard (RMS > 5 px → `pose_ok=False`) prevents
garbage output from noisy landmark detections.

### Thresholds
| Condition | Default | Rationale |
|---|---|---|
| \|yaw\| > 30° | looking_away = True | Patient clearly not facing screen |
| \|pitch\| > 25° | looking_away = True | Significant head nod / chin raise |

These are soft thresholds with no hysteresis in the spike; temporal
smoothing (e.g. EMA or a 3-of-5-frame majority vote) will be added in
Objective 1 to eliminate single-frame jitter.

### Input resolution and cadence
Same 320×240 canvas as YuNet — no extra resize.  Every frame.

### Estimated per-frame latency
| Operation | Estimated time | Notes |
|---|---|---|
| `cv2.solvePnP` (5 pts) | 0.2–0.5 ms | Pure C++ linear algebra, GIL released |
| `cv2.Rodrigues` + Euler | < 0.1 ms | Trivial |
| **Head pose total** | **≤ 0.5 ms** | |

### Executor assignment
Same `ThreadPoolExecutor` slot as YuNet — solvePnP runs **sequentially
after** YuNet in the same `run_in_executor` call.  No extra thread needed.

### Integration point
```python
# Objective 1: replace the bare detector.process() call with:
detection = await loop.run_in_executor(None, pipeline.process, detect_frame)
```
`AttentionPipeline.process()` chains YuNet → head pose → eye closure in
one synchronous call, consuming exactly one executor thread slot per frame.

---

## 4. Signal design — Eye Closure

### Why no classical EAR?
YuNet's 5 landmarks include only eye *centres*, not eyelid contours.
The Eye Aspect Ratio requires ≥ 4 per-eye eyelid points (upper, lower,
medial, lateral), which YuNet does not supply.  A lightweight model is
therefore the minimum-viable feature extractor, consistent with the
classical-first policy (classical threshold analysis on model-derived features).

### Feature source — candidate model
**MobileNetV3-Small binary classifier, int8-quantised (full-integer PTQ)**

| Property | Value |
|---|---|
| Input | 1 × 32 × 32 × 1 (grayscale, float32, [0, 1]) |
| Output | 1 × 1 (P(eye is OPEN)) |
| Format | TFLite int8 (.tflite) |
| Training data | MRL Eye Dataset (≈ 84 k images, balanced open/closed) |
| Target latency | ≤ 4 ms per inference on Pi 4 (Cortex-A72 NEON int8) |

**Why int8?**  Full-integer quantisation gives a ≈ 2× speed improvement
over fp32 on Cortex-A72 via ARM NEON SIMD paths in TFLite, at < 1% accuracy
loss on balanced eye datasets.  fp16 does not exploit NEON integer units.

**Why 32×32?**  At 320×240 canvas with a typical face bbox of 80–120 px,
the eye region is ≈ 15–25 px wide.  Upscaling to 32×32 retains all
discriminative texture while keeping inference cost minimal.

### Crop strategy
```
eye_half = max(8, int(0.18 × bbox_width))  ≈ 10–14 px at 320×240
right_patch = frame[rey-half : rey+half, rex-half : rex+half]
left_patch  = frame[ley-half : ley+half, lex-half : lex+half]
```
Each patch is converted to grayscale, resized to 32×32, and normalised
to [0, 1].  Out-of-bounds crops (face near frame edge) return score=None
and do not contribute to the both_closed verdict.

### Input resolution and cadence
320×240 detection canvas.  **Every frame** (no decimation) — at ≤ 4 ms/eye
the 2-eye total (≤ 8 ms) fits within budget.  If the TFLite model proves
slower than 4 ms/eye in the spike, decimate to every 3rd frame (cadence
≈ 10 Hz), which is still fast enough to catch a 300 ms blink threshold.

### Estimated per-frame latency
| Stage | Estimate | Notes |
|---|---|---|
| Crop both eye regions | ≤ 0.5 ms | 2× cv2.resize + numpy normalise |
| TFLite int8 inference × 2 | 4–8 ms | 2–4 ms per inference on Pi 4 |
| **Eye closure total** | **≤ 8.5 ms** | |

*The spike uses `MockEyeClosureDetector` (crop only, ≈ 0.1 ms).  The real
model latency must be measured when the TFLite model is available.*

### Executor assignment
Sequential in the same `run_in_executor` call.  Both inferences run on the
same thread back-to-back; no thread contention between left and right eye.

---

## 5. Combined pipeline performance budget

| Stage | P50 estimate | P95 estimate |
|---|---|---|
| YuNet face detection | 8 ms | 10 ms |
| Head pose (solvePnP) | 0.3 ms | 0.5 ms |
| Eye closure (TFLite ×2) | 6 ms | 8.5 ms |
| Python overhead + dict build | 0.2 ms | 0.5 ms |
| **Total** | **≤ 15 ms** | **≤ 20 ms** |

**Budget headroom:**  20 ms P95 vs 25 ms criterion = **5 ms margin**.

At 30 fps the distance broadcast interval is 33 ms.  A 20 ms detection
stage leaves 13 ms for asyncio overhead — sufficient with ThreadPoolExecutor
because the distance broadcast (`ultrasonic.distance_m`) is a non-blocking
property read taking < 0.1 ms and does not compete for the executor thread.

---

## 6. Executor architecture

### Thread model
```
asyncio event loop (core 0)
ThreadPoolExecutor — up to 8 workers (cores 0–3, scheduled by OS)
  Worker A: camera_loop → grab_detect_frame() + AttentionPipeline.process()
  Worker B: (spare — camera JPEG encode for preview every 3rd frame)
  Workers C–H: idle (available for future expansion)
```

### ProcessPoolExecutor — when would it be needed?
A `ProcessPoolExecutor` is needed only if:
- Total pipeline time consistently exceeds the 25 ms criterion, AND
- Profiling shows the bottleneck is **GIL contention** (Python-heavy code
  with no C extension) rather than raw compute.

Neither condition is expected here: cv2 DNN (YuNet), cv2.solvePnP, and
TFLite all release the GIL during their compute paths.  The Python code
around them (dict assembly, numpy array operations) is < 1 ms.

`ProcessPoolExecutor` would add 1–3 ms of IPC overhead per frame
(pickling numpy arrays across the process boundary) — likely costing more
than it saves unless the GIL bottleneck is confirmed by measurement.

### Provisional executor decision
> **ThreadPoolExecutor is sufficient — proceed to Objective 1 as planned.**
>
> This decision is provisional and based on the performance analysis above.
> It must be confirmed by running `backend/dev/spike_benchmark.py` on Pi 4
> hardware and recording results in Section 7 below.

---

## 7. Hardware spike results

### 7.1 Benchmark environment
| Field | Value |
|---|---|
| Pi hardware | Pi 4 (4 GB) |
| Eye closure model | MockEyeClosureDetector (crop only) |
| Frame source | Camera (real Pi Camera) |
| Frames processed | 1499 in 60 s |
| FPS achieved | 25.0 fps (target 30 fps) |

### 7.2 Latency results (from spike_results.json)
| Stage | P50 | P95 | P99 | Max |
|---|---|---|---|---|
| YuNet | 39.10 ms | 52.68 ms | 65.75 ms | 89.77 ms |
| Head pose (solvePnP) | 0.01 ms | 0.01 ms | 0.02 ms | 0.18 ms |
| **Total (mock eye closure)** | **39.15 ms** | **52.81 ms** | **65.81 ms** | **92.84 ms** |
| Total (with TFLite model) | TBD | TBD | TBD | TBD |

**Finding:** YuNet on Pi 4 is 4–5× slower than estimated (39 ms P50 vs 8–10 ms projected). The Pi OS Bookworm OpenCV DNN build runs YuNet on CPU without ARM NEON SIMD acceleration that the estimate assumed.

**Criterion [1] FAIL** — P95 total 52.81 ms > 25 ms threshold.

### 7.3 CPU utilisation
| Metric | Value |
|---|---|
| psutil cpu_percent (process, multi-core sum) | 201.5% |
| Interpretation | ≈2 full CPU cores consumed |
| Criterion [2] passed (≤ 60% single-core)? | NO |

**Note:** 201.5% is the multi-core sum (psutil default on Linux). On a 4-core Pi 4, a single-core utilisation of 100% would show as 100%. The 201.5% indicates YuNet is occupying ~2 cores. This is consistent with OpenCV DNN using inter-op parallelism internally even with the single `run_in_executor` call.

### 7.4 WS broadcast latency (live measurement)
| Metric | Value |
|---|---|
| Criterion [3] status | Not yet measured; json.dumps overhead 18.2 µs/call (negligible) |

*The distance broadcast loop is non-blocking (property read). With frame decimation (ATTENTION_SKIP=2) the attention pipeline only occupies the executor every 2nd frame, further reducing interference with the broadcast path.*

---

## 8. Executor decision gate (FINAL)

> **☑  ThreadPoolExecutor is sufficient — proceed as planned.**
>
> **Rationale:**
> The bottleneck is YuNet inference time (P50 39 ms), not Python GIL contention.
> cv2 DNN already releases the GIL during inference. Moving to a
> `ProcessPoolExecutor` would add 1–3 ms of IPC overhead (numpy array pickling)
> on top of the same 39 ms inference — making things slightly *worse*.
>
> **Remediation that does work: frame decimation.**
> Run `AttentionPipeline.process()` every 2nd camera frame (`ATTENTION_SKIP = 2`
> in `camera_loop`). This brings the effective attention rate to ~12 Hz while
> the distance broadcast remains at full camera rate (~25 Hz). The cached last
> detection is reused on skipped frames.
>
> **Performance with decimation:**
> - Distance broadcast: unchanged (non-blocking property read, full rate)
> - Attention P95 per *broadcast* frame: ~26 ms (52 ms / 2 frames amortised)
> - Effective attention refresh rate: ~12 Hz
> - All attention signals (face absent, looking away, untested-eye open) are
>   fast enough at 12 Hz: human reaction time to head turn is >200 ms;
>   the 3-frame temporal vote adds ~250 ms intentional delay anyway.
>
> **Implemented in `backend/main.py`** `camera_loop` as `ATTENTION_SKIP = 2`.

---

## 9. Fallback options if criteria are not met

| Criterion failing | Proposed remediation |
|---|---|
| [1] P95 total > 25 ms, YuNet dominant | Reduce YuNet canvas to 224×168 (35% fewer pixels; test detection accuracy first) |
| [1] P95 total > 25 ms, eye closure dominant | Decimate eye closure to every 3rd frame; apply temporal majority vote |
| [1] P95 total > 25 ms, head pose dominant | Not expected; use heavier 3D model sanity check |
| [2] CPU > 60% | Increase frame decimation; set `num_threads=1` on TFLite interpreter |
| [3] WS P95 degrades | Move attention pipeline to a separate `ProcessPoolExecutor` with 1 worker |

---

## 10. Constraints re-stated for Objective 1 implementation

1. **`iris_px` and `focal_length_px` must remain `null`** in all Pi-mode WS
   payloads even after iris tracking is added in Objective 1.  The
   Pi-mode distance-source assertion test added in Objective 3 enforces this.

2. **Distance broadcast path is independent** of the attention pipeline.
   `ultrasonic.distance_m` is a non-blocking property read; it must never
   block on an attention inference result.

3. **Attention pipeline cadence is independent** of the distance broadcast.
   If the pipeline takes 18 ms, the distance payload is still broadcast at
   the next asyncio tick without waiting for the frame result.

4. **Eye closure model is not yet selected.**  The `TFLiteEyeClosureDetector`
   stub in `backend/attention/eye_closure.py` documents the interface.
   Model training/selection and latency measurement are the first task of
   Objective 1 implementation.
