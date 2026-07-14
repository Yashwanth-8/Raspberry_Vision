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
CERT_DIR="$FRONTEND_DIR/certificates"
CERT_FILE="$CERT_DIR/nadi.pem"
KEY_FILE="$CERT_DIR/nadi-key.pem"
HTTPS_PORT=3443

# Detect the correct Chromium binary (name differs across Pi OS builds)
if command -v chromium-browser &>/dev/null; then
    CHROMIUM_BIN="chromium-browser"
elif command -v chromium &>/dev/null; then
    CHROMIUM_BIN="chromium"
else
    echo "ERROR: Chromium not found. Install with: apt-get install -y chromium-browser"
    exit 1
fi

# ---- Detect local IP ----
PI_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
if [ -z "$PI_IP" ]; then PI_IP="127.0.0.1"; fi

# ---- Generate SSL certificate with current IP as Subject Alt Name ----
# Required so phones on the local network can trust the HTTPS connection.
# A new cert is generated each boot to capture any IP change (DHCP).
mkdir -p "$CERT_DIR"
SSL_CONF=$(mktemp)
cat > "$SSL_CONF" << SSLEOF
[req]
distinguished_name = dn
x509_extensions    = v3_req
prompt             = no

[dn]
CN = nadi.local

[v3_req]
subjectAltName = IP:${PI_IP},DNS:localhost,DNS:nadi.local
SSLEOF

openssl req -x509 -newkey rsa:2048 \
    -keyout "$KEY_FILE" -out "$CERT_FILE" \
    -days 365 -nodes -config "$SSL_CONF" 2>/dev/null
rm -f "$SSL_CONF"

echo "=============================="
echo " Nadi Hardware Startup Script"
echo "=============================="

# ---- Start Python backend ----
echo "[1/2] Starting Python backend (WebSocket server on :8765)..."
cd "$BACKEND_DIR"
# Use venv Python directly
"$BACKEND_DIR/.venv/bin/python3" main.py &
BACKEND_PID=$!
echo "      Backend PID: $BACKEND_PID"

# Give backend a few seconds to initialise camera + face detector
sleep 3

# ---- Start Next.js frontend ----
echo "[2/2] Starting Next.js frontend..."
cd "$FRONTEND_DIR"
npm run start &
FRONTEND_PID=$!
echo "      Frontend PID: $FRONTEND_PID"

# Give Next.js 5 seconds to spin up
sleep 5

# ---- Start HTTPS proxy for phone / LAN access ----
# Phones need HTTPS for camera APIs. The Pi kiosk uses plain http://localhost:3000
# (localhost is a secure context), while phones use https://PI_IP:3443.
echo "Starting HTTPS proxy (port $HTTPS_PORT → 3000) for LAN access..."
local-ssl-proxy \
    --source "$HTTPS_PORT" \
    --target 3000 \
    --cert "$CERT_FILE" \
    --key "$KEY_FILE" &
PROXY_PID=$!
echo "      HTTPS proxy PID: $PROXY_PID"

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
echo "  Backend  PID : $BACKEND_PID"
echo "  Frontend PID : $FRONTEND_PID"
echo "  HTTPS proxy  : $PROXY_PID"
echo "  Chromium PID : $CHROMIUM_PID"
echo ""
echo "  Kiosk  (Pi screen) : http://localhost:3000"
echo "  Phone  (LAN access): https://${PI_IP}:${HTTPS_PORT}"
echo "  (On the phone: accept the self-signed certificate warning once)"
echo ""
echo "Press Ctrl+C to stop everything."

# Trap and kill all children on exit
cleanup() {
    echo "Shutting down..."
    kill "$BACKEND_PID" "$FRONTEND_PID" "$PROXY_PID" "$CHROMIUM_PID" 2>/dev/null || true
    exit 0
}
trap cleanup INT TERM

# Wait forever
wait
