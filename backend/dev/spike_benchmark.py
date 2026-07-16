"""
Objective 4 — Pi 4 spike benchmark harness.

Run this script on the Raspberry Pi 4 to measure the full attention pipeline
and fill in the Objective 4 executor decision gate in:
  Nadi_hardware/dev/obj4-architecture-design.md

Usage
-----
    # From the Nadi_hardware/backend/ directory:
    python3 dev/spike_benchmark.py

    # Custom duration and output file:
    python3 dev/spike_benchmark.py --duration 60 --output results.json

    # Dry-run without camera (generates synthetic frames for profiling):
    python3 dev/spike_benchmark.py --synthetic

Output
------
Prints a structured report to stdout and optionally saves JSON.
The report includes per-frame latency percentiles, estimated CPU
utilisation, and an explicit executor gate recommendation.

Acceptance criteria (from the plan)
-------------------------------------
  [1]  Total attention inference ≤ 25 ms/frame at 320×240
  [2]  CPU utilisation ≤ 60% single-core averaged over 10 s
  [3]  No measurable degradation in P95 WS broadcast latency

Criterion [3] requires running `spike_benchmark_ws.py` separately
(see comments at the bottom of this file).  This script covers [1] and [2].
"""

import argparse
import json
import os
import sys
import time
from typing import List, Optional

import cv2
import numpy as np

# ---------------------------------------------------------------------------
# Path setup — allow running from backend/ or backend/dev/
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_HERE)
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from face_detection import FaceDetector
from attention.head_pose import HeadPoseEstimator
from attention.eye_closure import MockEyeClosureDetector
from attention.pipeline import AttentionPipeline
from constants import DETECT_WIDTH, DETECT_HEIGHT

# Optional CPU monitoring
try:
    import psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False

# ---------------------------------------------------------------------------
# Benchmark configuration
# ---------------------------------------------------------------------------

DEFAULT_DURATION_S = 30
WARMUP_FRAMES      = 30    # discard first N frames (JIT / cache warm-up)
PRINT_EVERY        = 50    # print a progress line every N frames


# ---------------------------------------------------------------------------
# Camera / synthetic frame source
# ---------------------------------------------------------------------------

def _open_camera() -> Optional[cv2.VideoCapture]:
    """Open Pi Camera or webcam via OpenCV VideoCapture."""
    for idx in range(4):
        cap = cv2.VideoCapture(idx)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH,  DETECT_WIDTH)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, DETECT_HEIGHT)
            cap.set(cv2.CAP_PROP_FPS, 30)
            print(f"  Camera opened at index {idx}")
            return cap
    return None


def _synthetic_frame() -> np.ndarray:
    """Generate a 320×240 BGR frame with a fake face-like gradient."""
    frame = np.zeros((DETECT_HEIGHT, DETECT_WIDTH, 3), dtype=np.uint8)
    # Draw a flesh-tone ellipse (unlikely to trigger YuNet but realistic CPU load)
    cx, cy = DETECT_WIDTH // 2, DETECT_HEIGHT // 2
    cv2.ellipse(frame, (cx, cy), (50, 65), 0, 0, 360, (120, 160, 200), -1)
    return frame


# ---------------------------------------------------------------------------
# CPU measurement helpers
# ---------------------------------------------------------------------------

class CpuMonitor:
    """
    Measures single-core CPU utilisation for the current process over a window.

    Uses psutil when available; falls back to a process_time / wall_time ratio
    which approximates utilisation for a single-threaded workload.
    """

    def __init__(self) -> None:
        self._start_wall  = time.monotonic()
        self._start_proc  = time.process_time()
        self._psutil_proc = psutil.Process() if _PSUTIL else None

    def utilisation_pct(self) -> float:
        """Estimated CPU utilisation (%) since this monitor was created."""
        if self._psutil_proc is not None:
            try:
                return self._psutil_proc.cpu_percent(interval=None)
            except Exception:
                pass
        # Fallback: process_time / (wall_time × cpu_count) — rough estimate
        elapsed_wall = time.monotonic() - self._start_wall
        elapsed_proc = time.process_time() - self._start_proc
        if elapsed_wall <= 0:
            return 0.0
        cpu_count = os.cpu_count() or 1
        return min(100.0, (elapsed_proc / (elapsed_wall * cpu_count)) * 100.0)


# ---------------------------------------------------------------------------
# Latency statistics
# ---------------------------------------------------------------------------

def _percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    sorted_v = sorted(values)
    idx = int(len(sorted_v) * p / 100)
    return sorted_v[min(idx, len(sorted_v) - 1)]


def _format_ms(v: Optional[float]) -> str:
    return f"{v:.2f} ms" if v is not None else "N/A"


# ---------------------------------------------------------------------------
# WS broadcast latency simulation
# ---------------------------------------------------------------------------

def _simulate_ws_broadcast_latency_us() -> float:
    """
    Simulate the latency of json.dumps + asyncio task overhead.

    This is a rough proxy for the WS broadcast path; it does not replace the
    real P95 measurement described in the architecture document.  For the real
    measurement, run both the backend and a local WS client and record RTT.
    """
    import json
    payload = {
        "type": "frame",
        "face_detected": True, "face_count": 1,
        "attention_ok": True, "attention_reason": "ok",
        "distance": 0.6000, "raw_distance": 0.7200,
        "confidence": 1.0, "iris_px": None, "focal_length_px": None,
        "yaw_deg": 2.3, "pitch_deg": -1.1, "pose_ok": True,
        "left_eye_open": True, "right_eye_open": True, "both_closed": False,
    }
    t0 = time.monotonic()
    for _ in range(1000):
        json.dumps(payload)
    return ((time.monotonic() - t0) / 1000) * 1e6   # microseconds per call


# ---------------------------------------------------------------------------
# Main benchmark
# ---------------------------------------------------------------------------

def run_benchmark(
    duration_s: int = DEFAULT_DURATION_S,
    synthetic: bool = False,
    output_path: Optional[str] = None,
) -> dict:
    print("\n" + "=" * 60)
    print("  Nadi Vision — Objective 4 Spike Benchmark")
    print("=" * 60)
    print(f"  Duration     : {duration_s} s")
    print(f"  Frame source : {'synthetic (no camera)' if synthetic else 'camera'}")
    print(f"  psutil       : {'available' if _PSUTIL else 'not installed (fallback CPU estimate)'}")
    if not _PSUTIL:
        print("  Install psutil for accurate CPU measurement: pip3 install psutil")
    print()

    # --- Setup ---
    cap = None
    if not synthetic:
        print("  Opening camera…")
        cap = _open_camera()
        if cap is None:
            print("  WARNING: no camera found — falling back to synthetic frames")
            synthetic = True

    print("  Loading YuNet detector…")
    detector = FaceDetector(max_num_faces=2, score_threshold=0.6)
    head_pose = HeadPoseEstimator()
    eye_closure = MockEyeClosureDetector()  # replace with TFLiteEyeClosureDetector in Obj 1
    pipeline = AttentionPipeline(detector, head_pose, eye_closure)
    print("  Pipeline ready.\n")

    # --- Warm-up ---
    print(f"  Warming up ({WARMUP_FRAMES} frames)…")
    for _ in range(WARMUP_FRAMES):
        frame = _synthetic_frame() if synthetic else _grab_frame(cap)
        pipeline.process(frame)
    print()

    # --- Benchmark loop ---
    frame_latencies_ms: List[float]       = []
    yunet_latencies_ms: List[float]       = []
    pose_latencies_ms:  List[float]       = []
    total_latencies_ms: List[float]       = []

    cpu_monitor = CpuMonitor()
    if _PSUTIL:
        cpu_monitor._psutil_proc.cpu_percent(interval=None)  # prime reading

    deadline = time.monotonic() + duration_s
    frame_count = 0

    while time.monotonic() < deadline:
        frame = _synthetic_frame() if synthetic else _grab_frame(cap)

        # ---- Time the full pipeline ----
        t0 = time.monotonic()

        # Stage 1: YuNet
        t_yunet_start = time.monotonic()
        face = detector.process(frame)
        t_yunet = (time.monotonic() - t_yunet_start) * 1000

        # Stage 2: head pose
        t_pose_start = time.monotonic()
        landmarks = face.get("landmarks_2d")
        pose = head_pose.estimate(landmarks)
        t_pose = (time.monotonic() - t_pose_start) * 1000

        # Stage 3: eye closure (mock — add real model timing in Obj 1)
        bbox = face.get("bbox")
        eye_closure.detect(frame, landmarks, bbox)

        total_ms = (time.monotonic() - t0) * 1000

        yunet_latencies_ms.append(t_yunet)
        pose_latencies_ms.append(t_pose)
        total_latencies_ms.append(total_ms)

        frame_count += 1
        if frame_count % PRINT_EVERY == 0:
            cpu_est = cpu_monitor.utilisation_pct()
            print(
                f"  Frame {frame_count:>5}  |  "
                f"total: {total_ms:5.1f} ms  "
                f"yunet: {t_yunet:5.1f} ms  "
                f"pose: {t_pose:4.1f} ms  "
                f"cpu≈{cpu_est:.0f}%"
            )

    if cap:
        cap.release()

    cpu_final_pct = cpu_monitor.utilisation_pct()
    ws_latency_us = _simulate_ws_broadcast_latency_us()

    # --- Compile report ---
    report = _compile_report(
        frame_count=frame_count,
        duration_s=duration_s,
        yunet_ms=yunet_latencies_ms,
        pose_ms=pose_latencies_ms,
        total_ms=total_latencies_ms,
        cpu_pct=cpu_final_pct,
        ws_latency_us=ws_latency_us,
        synthetic=synthetic,
    )

    _print_report(report)

    if output_path:
        with open(output_path, "w") as f:
            json.dump(report, f, indent=2)
        print(f"\n  Results saved to {output_path}")

    return report


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _grab_frame(cap: cv2.VideoCapture) -> np.ndarray:
    ret, frame = cap.read()
    if not ret or frame is None:
        return _synthetic_frame()
    if frame.shape[:2] != (DETECT_HEIGHT, DETECT_WIDTH):
        frame = cv2.resize(frame, (DETECT_WIDTH, DETECT_HEIGHT))
    return frame


def _compile_report(
    frame_count: int,
    duration_s: int,
    yunet_ms: List[float],
    pose_ms: List[float],
    total_ms: List[float],
    cpu_pct: float,
    ws_latency_us: float,
    synthetic: bool,
) -> dict:
    def stats(lst: List[float]) -> dict:
        if not lst:
            return {}
        return {
            "p50_ms":  round(_percentile(lst, 50), 2),
            "p95_ms":  round(_percentile(lst, 95), 2),
            "p99_ms":  round(_percentile(lst, 99), 2),
            "mean_ms": round(sum(lst) / len(lst), 2),
            "max_ms":  round(max(lst), 2),
        }

    # Gate pass/fail
    p95_total = _percentile(total_ms, 95)
    gate = {
        "criterion_1_latency_ok": p95_total <= 25.0,
        "criterion_2_cpu_ok":     cpu_pct   <= 60.0,
        "criterion_3_ws_note":    (
            "Requires live WS measurement — see architecture design doc. "
            f"json.dumps overhead: {ws_latency_us:.1f} µs/call (negligible)."
        ),
    }
    all_hw_criteria_met = gate["criterion_1_latency_ok"] and gate["criterion_2_cpu_ok"]

    executor_decision = (
        "ThreadPoolExecutor is sufficient — proceed to Objective 1 as planned."
        if all_hw_criteria_met else
        "REVIEW REQUIRED: one or more acceptance criteria failed. "
        "See gate analysis in architecture design document before proceeding."
    )

    return {
        "meta": {
            "frame_count":    frame_count,
            "duration_s":     duration_s,
            "fps_achieved":   round(frame_count / duration_s, 1),
            "synthetic":      synthetic,
            "psutil_available": _PSUTIL,
        },
        "latency": {
            "yunet":  stats(yunet_ms),
            "pose":   stats(pose_ms),
            "total":  stats(total_ms),
            "eye_closure_note": (
                "Eye closure stage used MockEyeClosureDetector (crop only, ~0.1 ms). "
                "Re-run after plugging in TFLiteEyeClosureDetector in Objective 1."
            ),
        },
        "cpu": {
            "estimated_pct":  round(cpu_pct, 1),
            "note": (
                "psutil measurement" if _PSUTIL
                else "process_time/wall_time ratio — install psutil for accuracy"
            ),
        },
        "gate": gate,
        "executor_decision": executor_decision,
    }


def _print_report(r: dict) -> None:
    print("\n" + "=" * 60)
    print("  BENCHMARK REPORT")
    print("=" * 60)

    m = r["meta"]
    print(f"\n  Frames processed : {m['frame_count']}  ({m['fps_achieved']} fps)")
    print(f"  Frame source     : {'synthetic' if m['synthetic'] else 'camera'}")

    lat = r["latency"]
    print("\n  --- Per-stage latency ---")
    for stage, key in [("YuNet detection", "yunet"), ("Head pose (solvePnP)", "pose"), ("Total pipeline", "total")]:
        s = lat[key]
        print(f"  {stage:<25}  P50={s['p50_ms']:>6} ms  P95={s['p95_ms']:>6} ms  P99={s['p99_ms']:>6} ms")
    print(f"\n  {lat['eye_closure_note']}")

    print(f"\n  --- CPU utilisation ---")
    print(f"  Estimated: {r['cpu']['estimated_pct']}%  ({r['cpu']['note']})")

    print("\n  --- Executor gate ---")
    g = r["gate"]
    c1 = "PASS ✓" if g["criterion_1_latency_ok"] else "FAIL ✗"
    c2 = "PASS ✓" if g["criterion_2_cpu_ok"]     else "FAIL ✗"
    p95 = lat["total"]["p95_ms"]
    cpu = r["cpu"]["estimated_pct"]
    print(f"  [1] P95 total latency ≤ 25 ms  :  {p95} ms  → {c1}")
    print(f"  [2] CPU utilisation ≤ 60%       :  {cpu}%   → {c2}")
    print(f"  [3] P95 WS latency (live meas.) :  {g['criterion_3_ws_note']}")
    print(f"\n  DECISION: {r['executor_decision']}")
    print("=" * 60 + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Objective 4 spike benchmark — run on Pi 4"
    )
    parser.add_argument(
        "--duration", type=int, default=DEFAULT_DURATION_S,
        help=f"Benchmark duration in seconds (default: {DEFAULT_DURATION_S})"
    )
    parser.add_argument(
        "--synthetic", action="store_true",
        help="Use synthetic frames instead of opening a camera"
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Save JSON report to this file path"
    )
    args = parser.parse_args()
    run_benchmark(
        duration_s=args.duration,
        synthetic=args.synthetic,
        output_path=args.output,
    )
