# Nadi Hardware — Raspberry Pi Setup & Test Guide

## What This Is

A split-architecture version of NadiVision for Raspberry Pi:
- **Python backend** (`backend/`) — reads Pi Camera, runs MediaPipe face detection, calculates distance, streams data over WebSocket to the frontend
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

## Step 4 — Install Python Backend Dependencies

SSH into the Pi or open a terminal.

First, install `uv` if not already present:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env
```

Then install backend dependencies:
```bash
cd /home/pi/Nadi_hardware/backend

# Use --system-site-packages so picamera2 (system-installed) is accessible
uv venv --system-site-packages
uv pip install -r requirements.txt
```

> **Note:** `picamera2` is pre-installed on Raspberry Pi OS Bookworm. The venv uses
> `--system-site-packages` so it can access picamera2 without pip-installing it
> (which would break it).

> **YuNet model:** On first run the backend automatically downloads the face
> detection model (~80 KB) from the OpenCV model zoo. Make sure the Pi has
> internet access for the first run.

Verify OpenCV is installed correctly:
```bash
uv run python -c "import cv2; print('OpenCV OK:', cv2.__version__)"
```

---

## Step 5 — Install Node.js Frontend Dependencies

```bash
# Install Node.js 20 LTS (if not already installed)
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs

# Verify
node --version   # should be v20.x.x
npm --version

# Install frontend dependencies
cd /home/pi/Nadi_hardware/frontend
npm install

# Build the production bundle (do this once)
npm run build
```

> Building on Pi 4 takes about 3–5 minutes. Do it once; subsequent starts use the cached build.

---

## Step 6 — Test Backend Alone

Make sure the camera works with the Python backend before adding the frontend:

```bash
cd /home/pi/Nadi_hardware/backend
uv run python main.py
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
│     ├── face_detection.py  ← MediaPipe FaceMesh (Python)
│     ├── distance.py        ← iris/IPD/face-width estimators
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
