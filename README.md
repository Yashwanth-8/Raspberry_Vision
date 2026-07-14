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
│  │  • Kalman-filtered distance from HC-SR04      │ │
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
| **HC-SR04 ultrasonic** | Measures patient distance from the screen. Used to auto-scale the optotype to the correct angular size — the test is valid at any sitting distance. |
| **Pi Camera** | Monitors attention integrity. Current prototype pauses on no-face or multiple-faces; fine-grained gaze/eye-state checks are planned. |

### Test flow

1. **Landing** — clinician selects eye, correction status, patient demographics
2. **Camera setup** — confirms sensor active, patient in position, live distance shown
3. **Stability lock** — waits 3 seconds of consistent distance before starting
4. **Tumbling E test** — 8 logMAR lines (20/200 → 20/16), 5 trials per line, random directions
5. **Results** — logMAR, ETDRS letter score, Snellen, WHO classification, CI, integrity flags

---

## Project Structure

```
Nadi_hardware/
├── backend/                  Python — runs on the Pi
│   ├── main.py               WebSocket server, camera + sensor loop
│   ├── camera.py             Pi Camera capture (picamera2, XRGB8888)
│   ├── face_detection.py     YuNet attention monitoring (320×240)
│   ├── ultrasonic.py         HC-SR04 distance sensor + median/Kalman filter
│   ├── kalman.py             1D Kalman filter
│   └── constants.py          GPIO pins, camera dims, thresholds
│
├── frontend/                 Next.js — runs in Chromium kiosk
│   └── src/
│       ├── components/screens/
│       │   ├── LandingScreen.tsx     Patient setup + auto screen calibration
│       │   ├── CameraSetupScreen.tsx Distance preview + position check
│       │   ├── TestScreen.tsx        Core visual acuity test
│       │   └── ResultsScreen.tsx     Clinical report + PDF export
│       └── lib/
│           ├── optotype.ts           E sizing mathematics (arcmin → px)
│           ├── hardware-ws.ts        WebSocket client for Pi backend
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
| Integrity | Flags for fast answers (<300ms), face loss >2s, multiple faces |

---

## Hardware Requirements

| Component | Spec |
|---|---|
| Raspberry Pi 4 (4GB) or Pi 5 | Pi 5 for smoother performance |
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

Frontend only (no backend needed — uses laptop webcam + MediaPipe JS):
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

## Current Status & Next Steps

This is the **prototype build for clinical validation**.

- [ ] Collect clinical validation data vs gold-standard optometry
- [ ] Physical enclosure with fixed sensor-to-screen calibration
- [ ] Calibrate `SENSOR_TO_EYE_OFFSET_M` in `constants.py` once mounted
- [ ] Evaluate Pi 5 upgrade for stable 30fps at 720p detection


## What This Is

A split-architecture version of NadiVision for Raspberry Pi:
- **Python backend** (`backend/`) — reads Pi Camera, runs OpenCV YuNet face detection for attention state, reads HC-SR04 distance, streams data over WebSocket to the frontend
- **Next.js frontend** (`frontend/`) — exact replica of the original app; receives distance/face data from backend via `ws://localhost:8765`; runs in Chromium kiosk mode

The frontend auto-detects whether the Python backend is running. If yes → **Pi mode** (camera handled by Python). If no → **browser mode** (original MediaPipe JS path, works on any laptop).

---

## Hardware Requirements

| Item | Notes |
|---|---|
| Raspberry Pi 4 (4 GB) or Pi 5 | Pi 5 recommended for smoother MediaPipe |
| Pi Camera Module 3 (or Module 2) | Connected via CSI ribbon cable |
| MicroSD card (32 GB+, Class 10) | With Raspberry Pi OS Bookworm (64-bit) |
| HDMI monitor + keyboard + mouse | For initial setup |
| Internet connection (Wi-Fi or Ethernet) | For first-time installs |

---

## Step 1 — Flash Raspberry Pi OS

1. Download **Raspberry Pi Imager** from [raspberrypi.com/software](https://raspberrypi.com/software/)
2. Flash **Raspberry Pi OS Bookworm (64-bit, Desktop)** to your SD card
3. In imager settings, enable SSH and set your username/password
4. Insert card, boot the Pi, complete initial setup

---

## Step 2 — Enable and Verify Pi Camera (Bookworm)

On Raspberry Pi OS Bookworm, the old Legacy Camera option is removed.
Use the rpicam/libcamera stack.

```bash
sudo apt update
sudo apt full-upgrade -y
sudo apt install -y rpicam-apps
sudo reboot
```

After reboot, test that the camera is detected:
```bash
rpicam-hello --list-cameras
rpicam-hello -t 3000
```
You should see at least one detected camera and a 3-second preview window.

If no camera is detected, power off the Pi and reseat the ribbon cable, then test again.

---

## Step 3 — Transfer Project Files

On your laptop, from the `nadi_vscode/` folder:
```bash
scp -r Nadi_hardware pi@<PI_IP_ADDRESS>:/home/pi/
```

Or clone your repo directly on the Pi if you've pushed it to GitHub.

---

## Step 4 — Install Everything (One Script)

The repo includes a `setup.sh` that installs all backend and frontend
dependencies in one go. No `uv` required — uses standard system Python and pip.

```bash
cd /home/pi/Nadi_hardware
chmod +x setup.sh
./setup.sh
```

This script:
1. Installs system packages (`python3-opencv`, `python3-numpy`, `python3-pip`, `curl`, Node.js 20)
2. Creates a Python venv at `backend/.venv` with `--system-site-packages`
3. Installs `websockets` via pip
4. Downloads the YuNet face detection model (~80 KB)
5. Runs `npm install` and `npm run build` for the frontend
6. Makes `start.sh` executable

> **Note:** `picamera2` is pre-installed on Raspberry Pi OS Bookworm. The venv uses
> `--system-site-packages` so it can access picamera2, opencv, and numpy from the system.

Verify after setup:
```bash
cd /home/pi/Nadi_hardware/backend
.venv/bin/python3 -c "import cv2; print('OpenCV OK:', cv2.__version__)"
.venv/bin/python3 -c "import websockets; print('websockets OK:', websockets.__version__)"
```

---

## Step 5 — Test Backend Alone

Make sure the camera works with the Python backend before adding the frontend:

```bash
cd /home/pi/Nadi_hardware/backend
.venv/bin/python3 main.py
```

Expected output:
```
2026-xx-xx [INFO] Starting Nadi Hardware backend...
2026-xx-xx [INFO] Pi Camera started (1280x720)
2026-xx-xx [INFO] WebSocket server listening on ws://0.0.0.0:8765
[FaceDetector] Downloading YuNet model → ... (~80 KB)…  ← first run only
[FaceDetector] Model downloaded OK.                      ← first run only
2026-xx-xx [INFO] Face detector (YuNet) loaded
```

Sit in front of the camera. You should see logs like:
```
2026-xx-xx [INFO] Client connected: ...
```

Press `Ctrl+C` to stop.

---

## Step 7 — Test Frontend Alone (Browser Mode)

With backend **not** running, test that the Next.js app still works in fallback browser mode:

```bash
cd /home/pi/Nadi_hardware/frontend
npm run start
```

Open Chromium and go to `http://localhost:3000`. The app should load and use the browser camera directly (no Pi backend needed). This confirms the frontend is correctly built.

---

## Step 8 — Full Integration Test

Run backend and frontend together:

```bash
# Make start script executable (first time only)
chmod +x /home/pi/Nadi_hardware/start.sh

# Run everything
cd /home/pi/Nadi_hardware
./start.sh
```

This starts:
1. Python backend (WebSocket on `:8765`)
2. Next.js production server (HTTP on `:3000`)
3. Chromium browser in kiosk mode pointing to `localhost:3000`

**What to check:**
- On the Camera Setup screen, you should see **"Pi Camera"** badge (not "Camera Active")
- The face detection and distance readout should update in real time
- No browser camera permission popup should appear (camera is handled by Python)

---

## Step 9 — Set Up Auto-Start on Boot (Optional)

To launch automatically when the Pi boots:

```bash
mkdir -p /home/pi/.config/autostart
cat > /home/pi/.config/autostart/nadi.desktop << 'EOF'
[Desktop Entry]
Type=Application
Name=NadiVision
Exec=/home/pi/Nadi_hardware/start.sh
X-GNOME-Autostart-enabled=true
EOF
```

---

## Troubleshooting

### Camera not detected
```bash
# List detected cameras
rpicam-hello --list-cameras

# Preview test
rpicam-hello -t 3000
```

If `--list-cameras` shows no camera:
- Fully power off the Pi and unplug power.
- Reseat the CSI ribbon cable on both Pi and camera module.
- Boot and test again.

Check auto-detect setting:
```bash
grep -n camera_auto_detect /boot/firmware/config.txt
```
It should contain:
```bash
camera_auto_detect=1
```

For deeper diagnostics:
```bash
dmesg | grep -Ei "unicam|imx|ov|camera|csi"
```

### WebSocket connection refused in frontend
- Ensure the backend is running before opening the frontend
- Check `start.sh` — it waits 3 seconds for the backend to init before launching the frontend
- Check firewall: `sudo ufw status` — port 8765 should be open (or ufw inactive)

### MediaPipe too slow / low FPS
On Pi 4, MediaPipe Python runs at ~10–15 fps. This is sufficient for distance estimation. To improve:
```bash
# Check CPU temperature — throttling causes slowdowns
vcgencmd measure_temp
# If > 80°C, add a heatsink or fan
```

### Frontend stuck on "Detecting Pi mode..."
The app waits up to 5 seconds for the WebSocket connection. If the backend starts slower than expected:
- Wait a few more seconds — it will fall back to browser mode if the backend is not ready
- Check the backend is running: `ps aux | grep python`

### `npm run build` fails on Pi
```bash
# Increase Node.js memory limit
export NODE_OPTIONS="--max-old-space-size=1024"
npm run build
```

---

## Architecture Summary

```
Raspberry Pi
├── backend/main.py          ← WebSocket server (ws://localhost:8765)
│     ├── camera.py          ← picamera2 frame capture
│     ├── face_detection.py  ← OpenCV YuNet attention monitor (Python)
│     ├── ultrasonic.py      ← HC-SR04 distance + filtering
│     └── kalman.py          ← 1D Kalman filter
│
└── frontend/                ← Next.js React app (http://localhost:3000)
      └── src/lib/
            └── hardware-ws.ts  ← WebSocket client hook
                                   (auto-detects Pi vs browser mode)
```

Distance flows: `Pi Camera → Python → WebSocket → React Zustand store → test logic`

The test logic, scoring, UI, and PDF export are all unchanged from the original app.

---

## Verified Working Configuration

| Component | Version |
|---|---|
| Raspberry Pi OS | Bookworm (Debian 12, 64-bit) |
| Python | 3.11+ |
| Node.js | 20 LTS |
| picamera2 | pre-installed with OS |
| mediapipe | removed — replaced by OpenCV YuNet |
| websockets | 12.x |
| Next.js | 16.x |
