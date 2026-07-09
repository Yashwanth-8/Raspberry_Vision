#!/usr/bin/env bash
# start.sh — Start both backend and frontend on Raspberry Pi
# Run from the Nadi_hardware/ directory: ./start.sh

set -e

# Ensure local binaries (uv, node, npm) are in PATH.
# Required when launched from autostart .desktop files or restricted shells.
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend"

# Detect the correct Chromium binary (name differs across Pi OS builds)
if command -v chromium-browser &>/dev/null; then
    CHROMIUM_BIN="chromium-browser"
elif command -v chromium &>/dev/null; then
    CHROMIUM_BIN="chromium"
else
    echo "ERROR: Chromium not found. Install with: apt-get install -y chromium-browser"
    exit 1
fi

echo "=============================="
echo " Nadi Hardware Startup Script"
echo "=============================="

# ---- Start Python backend ----
echo "[1/2] Starting Python backend (WebSocket server on :8765)..."
cd "$BACKEND_DIR"
# Use venv Python directly — works regardless of whether uv is in PATH
"$BACKEND_DIR/.venv/bin/python" main.py &
BACKEND_PID=$!
echo "      Backend PID: $BACKEND_PID"

# Give backend 3 seconds to initialise camera + MediaPipe
sleep 3

# ---- Start Next.js frontend ----
echo "[2/2] Starting Next.js frontend..."
cd "$FRONTEND_DIR"
npm run start &
FRONTEND_PID=$!
echo "      Frontend PID: $FRONTEND_PID"

# Give Next.js 5 seconds to spin up
sleep 5

# ---- Open Chromium in kiosk mode ----
echo "Opening Chromium in kiosk mode..."
"$CHROMIUM_BIN" \
    --kiosk \
    --noerrdialogs \
    --disable-infobars \
    --no-first-run \
    --disable-translate \
    --disable-features=TranslateUI \
    --disable-session-crashed-bubble \
    --autoplay-policy=no-user-gesture-required \
    http://localhost:3000 &
CHROMIUM_PID=$!

echo ""
echo "All services started."
echo "  Backend  PID: $BACKEND_PID"
echo "  Frontend PID: $FRONTEND_PID"
echo "  Chromium PID: $CHROMIUM_PID"
echo ""
echo "Press Ctrl+C to stop everything."

# Trap and kill all children on exit
cleanup() {
    echo "Shutting down..."
    kill "$BACKEND_PID" "$FRONTEND_PID" "$CHROMIUM_PID" 2>/dev/null || true
    exit 0
}
trap cleanup INT TERM

# Wait forever
wait
