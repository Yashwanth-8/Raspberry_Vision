# Nadi Vision — Hardware Edition

> **Clinical-grade visual acuity screening on a Raspberry Pi**

---

## What is Nadi Vision?

Nadi Vision is an AI-assisted visual acuity testing device designed to bring clinical-quality eye screening to primary healthcare settings, community health workers, and resource-constrained environments where traditional optometry infrastructure is unavailable or unaffordable.

The goal is to make a **20/20-line logMAR vision test** as simple as pressing a button — no trained optometrist required for the screening step, no expensive equipment, and no paper charts.

---

## The Problem We Are Solving

Globally, over **2.2 billion people** have near or distance vision impairment. A significant proportion involve conditions that are **preventable or correctable** (refractive errors, cataracts) if caught early. In rural India and similar contexts:

- Access to qualified eye doctors is severely limited
- Traditional chart-based tests require a trained examiner
- Portable devices on the market cost thousands of dollars
- Screening at scale (school programs, rural camps) is logistically difficult

Nadi Vision addresses this by automating the measurement of **visual acuity (VA)** — the foundational metric in any eye exam — in a way that is low-cost, self-administered, and produces a clinically validated result.

---

## How It Works

```
┌─────────────────────────────────────────────────────┐
│                  Raspberry Pi 4                     │
│                                                     │
│  ┌─────────────┐    ┌──────────────────────────┐   │
│  │  HC-SR04    │    │      Pi Camera Module    │   │
│  │ Ultrasonic  │    │  (Attention Monitoring)  │   │
│  │  (Distance) │    └──────────────────────────┘   │
│  └─────────────┘              │                    │
│        │                      │ YuNet face detect  │
│        ▼                      ▼                    │
│  ┌───────────────────────────────────────────────┐ │
│  │         Python Backend  (WebSocket :8765)     │ │
│  │  • Median+EMA filtered distance (HC-SR04)     │ │
│  │  • Attention monitoring (face present/absent) │ │
│  │  • Real-time data stream to frontend          │ │
│  └───────────────────────────────────────────────┘ │
│                         │                           │
│                         ▼                           │
│  ┌───────────────────────────────────────────────┐ │
│  │      Next.js Frontend  (Chromium Kiosk)       │ │
│  │  • Tumbling E optotype (logMAR / ETDRS scale) │ │
│  │  • Auto-scales E size to exact angular specs  │ │
│  │  • Stability lock before each test            │ │
│  │  • Full clinical results report               │ │
│  └───────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

### Sensor roles

| Sensor | Role |
|---|---|
| **HC-SR04 ultrasonic** | Measures patient distance from the screen. Filtered through a Median(3)+EMA(α=0.7) pipeline — rejects wall-reflection spikes and smooths ±2cm noise to ±0.9cm. Used to auto-scale the optotype to the correct angular size. |
| **Pi Camera (YuNet)** | Monitors attention at 320×240. Pauses test if face leaves frame or a second person enters. 720p stream sent to browser as JPEG preview. |

### Test flow

1. **Landing** — clinician selects eye, correction status, patient demographics. Screen PPI auto-detected.
2. **Camera setup** — confirms HC-SR04 sensor is active, shows live distance and camera preview
3. **Stability lock** — waits 3 seconds of stable distance (±15cm threshold) before starting
4. **Tumbling E test** — 8 logMAR lines (20/200 → 20/16), 5 trials per line, random directions
5. **Results** — logMAR, ETDRS letter score, Snellen, WHO classification, CI, integrity flags

---

## Distance Filtering Pipeline

The HC-SR04 distance goes through two stages before reaching the frontend:

```
Raw reading (17 Hz)
    → if None or out-of-range (4cm–3.5m): skip
    → Median(3):  rejects wall-reflection spikes
    → EMA(α=0.7): smooths ±1.5cm residual to ±0.9cm
    → distance_m (streamed via WebSocket)
```

The Kalman filter used in earlier versions was replaced with this simpler, faster pipeline because HC-SR04 noise is spike-based (not Gaussian), making Kalman the wrong tool for this sensor.

---

## Project Structure

```
Nadi_hardware/
├── backend/                  Python — runs on the Pi
│   ├── main.py               WebSocket server, camera + sensor loop
│   ├── camera.py             Pi Camera capture (picamera2, XRGB8888 format)
│   ├── face_detection.py     YuNet attention monitoring (320×240 canvas)
│   ├── ultrasonic.py         HC-SR04 + Median(3)+EMA(α=0.7) filter
│   └── constants.py          GPIO pins, camera dims, attention thresholds
│
├── frontend/                 Next.js — runs in Chromium kiosk
│   └── src/
│       ├── components/screens/
│       │   ├── LandingScreen.tsx     Patient setup + auto screen calibration
│       │   ├── CameraSetupScreen.tsx Distance preview + position check
│       │   ├── TestScreen.tsx        Core visual acuity test
│       │   └── ResultsScreen.tsx     Clinical report
│       └── lib/
│           ├── optotype.ts           E sizing mathematics (arcmin → px)
│           ├── hardware-ws.ts        WebSocket client for Pi backend
│           ├── kalman.ts             Kalman filter (browser fallback path only)
│           └── store.ts              Zustand state management
│
├── setup.sh                  One-time install (deps, frontend build, model download)
├── start.sh                  Boot script (backend + frontend + HTTPS proxy + kiosk)
└── README.md                 This file
```

---

## Clinical Standards

Implemented to **ETDRS** standards:

| Parameter | Specification |
|---|---|
| Optotype | Tumbling E, 4 orientations |
| Scale | logMAR 1.0 → −0.1 (Snellen 20/200 → 20/16) |
| Lines | 8, with 5 trials per line |
| Scoring | Ferris et al. 1982 — 0.02 logMAR per correct letter |
| Pass criterion | ≥ 3 of 5 correct to advance |
| Distance | Auto-scaled from live HC-SR04 — valid at any sitting distance |
| Integrity flags | Fast answers (<300ms), face loss >2s, multiple faces, fullscreen exit |

---

## Hardware Requirements

| Component | Spec |
|---|---|
| Raspberry Pi 4 (4GB) | Current target; Pi 5 gives better performance headroom |
| Pi Camera Module 2 or 3 | CSI ribbon cable |
| HC-SR04 Ultrasonic Sensor | GPIO 23 (Trig) / GPIO 24 (Echo) |
| Resistors: 1kΩ + 2.2kΩ | Voltage divider on Echo pin (5V → 3.3V) |
| MicroSD 32 GB+ Class 10 | Raspberry Pi OS Bookworm 64-bit |
| HDMI display | Kiosk screen |

**HC-SR04 wiring:**
```
VCC  → Pin 2  (5V)
GND  → Pin 6  (GND)
TRIG → Pin 16 (GPIO 23)          direct
ECHO → 1kΩ → Pin 18 (GPIO 24) → 2.2kΩ → GND   (voltage divider: 5V → 3.3V)
```

---

## Quick Start

```bash
git clone https://github.com/Yashwanth-8/Raspberry_Vision.git
cd Raspberry_Vision

# One-time setup (installs deps, builds frontend, downloads YuNet model)
chmod +x setup.sh && ./setup.sh

# Start everything
./start.sh
```

- **Kiosk (Pi screen):** `http://localhost:3000`
- **Phone on same Wi-Fi:** `https://<Pi-IP>:3443` (accept self-signed cert once)

---

## Laptop Testing

Frontend only (no backend — uses laptop webcam + MediaPipe JS for distance):
```bash
cd frontend && npm install && npm run dev
```

Full backend simulation on Mac/Linux:
```bash
pip install websockets opencv-python
cd backend
MOCK_DISTANCE_M=0.6 python3 main.py   # simulates 0.6m HC-SR04 reading
```

---

## Engineering Decisions Made

| Decision | Rationale |
|---|---|
| **HC-SR04 for distance** | Replaces camera-based distance estimation (IPD/iris/face-width). Sensor gives ±3mm accuracy vs ±10–20cm from camera. Removes ~40ms of per-frame distance computation. |
| **Median+EMA instead of Kalman** | HC-SR04 noise is spike-based (wall reflections), not Gaussian. Kalman is optimal for Gaussian noise. Median rejects spikes; EMA smooths residual — simpler and better suited. |
| **Pi Camera at XRGB8888** | BGR888/RGB888 have inconsistent byte-order across Pi Camera Module 2 vs 3 on different libcamera versions. XRGB8888 delivers BGRX consistently — drop the X channel, always get correct BGR. |
| **YuNet at 320×240 fixed canvas** | Avoids OpenCV's `setInputSize` coordinate-scaling bug present in Pi OS Bookworm's older cv2 builds. Also keeps inference at ~8ms on Pi 4. |
| **Browser fallback (piMode=false)** | When no Pi backend is detected (laptop dev), the frontend falls back to MediaPipe JS + webcam. Same UI, different distance source. |

---

## Current Status

**Prototype build — ready for basic clinical validation testing.**

### Completed
- [x] HC-SR04 ultrasonic distance with Median+EMA filtering
- [x] Pi Camera XRGB8888 + YuNet face/multiple-face attention monitoring
- [x] ETDRS Tumbling E test (8 logMAR lines, fractional scoring)
- [x] Stability lock: test only starts after patient holds position 3s
- [x] Real-time E autoscaling during positioning (live distance → E size)
- [x] Test integrity flags (face loss, multiple faces, fast answers, fullscreen exit)
- [x] HTTPS proxy for phone/LAN access
- [x] Full clinical results report (logMAR, ETDRS, Snellen, WHO, CI)
- [x] Chromium kiosk mode autostart

### Next Steps
- [ ] Physical enclosure — fix sensor-to-screen offset, set `SENSOR_TO_EYE_OFFSET_M`
- [ ] Collect clinical validation data vs gold-standard optometry measurements
- [ ] Evaluate upgrade path: Pi 5 for better performance headroom

