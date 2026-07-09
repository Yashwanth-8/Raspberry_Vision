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
"$BACKEND_DIR/.venv/bin/pip3" install "websockets>=12.0,<14.0"

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

NODE_VERSION="v20.18.1"
ARCH="$(uname -m)"

# Install Node.js 20 LTS if not already present
if ! command -v node &>/dev/null || [[ "$(node --version)" != v20* ]]; then
    echo "      Installing Node.js 20 LTS..."

    if [ "$ARCH" = "armv7l" ] || [ "$ARCH" = "armv6l" ]; then
        # 32-bit ARM — NodeSource does not support armhf, use unofficial builds
        echo "      Detected 32-bit ARM ($ARCH) — using unofficial Node.js builds..."
        curl -fsSL "https://unofficial-builds.nodejs.org/download/release/${NODE_VERSION}/node-${NODE_VERSION}-linux-armv7l.tar.xz" -o /tmp/node.tar.xz
        sudo tar -xf /tmp/node.tar.xz -C /usr/local --strip-components=1
        rm -f /tmp/node.tar.xz
    elif [ "$ARCH" = "aarch64" ]; then
        # 64-bit ARM — NodeSource works
        curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
        sudo apt-get install -y nodejs
    else
        # x86_64 or other
        curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
        sudo apt-get install -y nodejs
    fi
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
echo " To test backend alone:"
echo "   cd $BACKEND_DIR"
echo "   .venv/bin/python3 main.py"
echo ""
