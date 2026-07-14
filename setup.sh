   #!/usr/bin/env bash
# setup.sh — One-time setup script for Nadi Hardware on Raspberry Pi
#
# Run this ONCE after cloning the repo on the Pi:
#   chmod +x setup.sh && ./setup.sh
#
# Works on Raspberry Pi OS Bullseye (Python 3.9) and Bookworm (Python 3.11+).
# Does NOT require uv. Uses system Python and pip.

set -e

echo "=============================="
echo " Nadi Hardware — Pi Setup"
echo "=============================="
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend"

# ---------------------------------------------------------------------------
# 1. System packages
# ---------------------------------------------------------------------------
echo "[1/5] Installing system packages..."
sudo apt-get update
sudo apt-get install -y \
    python3-pip \
    python3-venv \
    python3-numpy \
    python3-opencv \
    python3-gpiozero \
    python3-rpi.gpio \
    curl \
    git

echo "      Python version: $(python3 --version)"
echo "      OpenCV version: $(python3 -c 'import cv2; print(cv2.__version__)')"
echo ""

# ---------------------------------------------------------------------------
# 2. Python backend virtual environment
# ---------------------------------------------------------------------------
echo "[2/5] Setting up Python backend..."
cd "$BACKEND_DIR"

# Create venv with access to system-installed packages (numpy, opencv, picamera2)
python3 -m venv --system-site-packages .venv

# Activate and install remaining pip packages
"$BACKEND_DIR/.venv/bin/pip3" install --upgrade pip
"$BACKEND_DIR/.venv/bin/pip3" install "websockets>=12.0,<14.0" "gpiozero>=2.0"

echo "      Backend venv ready at: $BACKEND_DIR/.venv"
echo "      websockets: $("$BACKEND_DIR/.venv/bin/python3" -c 'import websockets; print(websockets.__version__)')"
echo ""

# ---------------------------------------------------------------------------
# 3. Download YuNet face detection model (~80 KB)
# ---------------------------------------------------------------------------
echo "[3/5] Downloading face detection model..."
MODEL_DIR="$BACKEND_DIR/models"
MODEL_FILE="$MODEL_DIR/face_detection_yunet_2023mar.onnx"
MODEL_URL="https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"

mkdir -p "$MODEL_DIR"
if [ ! -f "$MODEL_FILE" ]; then
    curl -L -o "$MODEL_FILE" "$MODEL_URL"
    echo "      Model downloaded: $MODEL_FILE"
else
    echo "      Model already exists: $MODEL_FILE"
fi
echo ""

# ---------------------------------------------------------------------------
# 4. Node.js and frontend
# ---------------------------------------------------------------------------
echo "[4/5] Setting up Node.js frontend..."

NODE_VERSION_ARM64="v20.18.1"
NODE_VERSION_ARMHF="v18.20.4"  # Node 18 still has official armv7l builds
ARCH="$(uname -m)"
# On Raspberry Pi, kernel can be 64-bit but userland 32-bit — check dpkg
DEB_ARCH="$(dpkg --print-architecture 2>/dev/null || echo "$ARCH")"

# Install Node.js if not already present
if ! command -v node &>/dev/null || [[ "$(node --version)" != v1[89]* && "$(node --version)" != v2* ]]; then
    echo "      Installing Node.js LTS..."
    echo "      Kernel arch: $ARCH | Userland arch: $DEB_ARCH"

    if [ "$DEB_ARCH" = "armhf" ] || [ "$ARCH" = "armv7l" ] || [ "$ARCH" = "armv6l" ]; then
        # 32-bit ARM userland — use official Node.js 18 armv7l builds
        echo "      Detected 32-bit ARM — using Node.js 18 LTS (official armv7l)..."
        curl -fsSL "https://nodejs.org/dist/${NODE_VERSION_ARMHF}/node-${NODE_VERSION_ARMHF}-linux-armv7l.tar.xz" -o /tmp/node.tar.xz
        sudo tar -xf /tmp/node.tar.xz -C /usr/local --strip-components=1
        rm -f /tmp/node.tar.xz
    elif [ "$DEB_ARCH" = "arm64" ] || [ "$ARCH" = "aarch64" ]; then
        # 64-bit ARM — NodeSource works
        curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
        sudo apt-get install -y nodejs
    else
        # x86_64 or other
        curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
        sudo apt-get install -y nodejs
    fi
    # Ensure /usr/local/bin is in PATH for this session
    export PATH="/usr/local/bin:$PATH"
fi

echo "      Node: $(node --version)"
echo "      npm:  $(npm --version)"

cd "$FRONTEND_DIR"
echo "      Running npm install..."
npm install

echo "      Building production bundle (this takes a few minutes on Pi)..."
export NODE_OPTIONS="--max-old-space-size=1024"
npm run build

echo "      Frontend build complete."

# Install local-ssl-proxy globally — used by start.sh to expose HTTPS on port 3443
# so phones on the local network can access the app (camera APIs require HTTPS).
echo "      Installing local-ssl-proxy (HTTPS proxy for LAN access)..."
npm install -g local-ssl-proxy
echo "      local-ssl-proxy: $(local-ssl-proxy --version 2>/dev/null || echo 'installed')"
echo ""

# ---------------------------------------------------------------------------
# 5. Make start script executable
# ---------------------------------------------------------------------------
echo "[5/5] Finalizing..."
chmod +x "$SCRIPT_DIR/start.sh"

echo ""
echo "=============================="
echo " Setup complete!"
echo "=============================="
echo ""
echo " To run the app:"
echo "   cd $SCRIPT_DIR"
echo "   ./start.sh"
echo ""
echo " Kiosk (Pi screen):   http://localhost:3000"
echo " Phone / LAN access:  https://<Pi-IP>:3443  (accept the self-signed cert warning)"
echo ""
echo " To test backend alone:"
echo "   cd $BACKEND_DIR"
echo "   .venv/bin/python3 main.py"
echo ""
