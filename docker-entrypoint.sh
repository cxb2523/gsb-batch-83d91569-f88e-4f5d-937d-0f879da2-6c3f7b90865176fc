#!/bin/bash
set -e

CONFIG_DIR="/config"
mkdir -p "$CONFIG_DIR"

# If HA_URL and HA_TOKEN are provided, create config.json
if [ -n "$HA_URL" ] && [ -n "$HA_TOKEN" ]; then
  if [ ! -f "$CONFIG_DIR/config.json" ]; then
    DEVICE_NAME="${DEVICE_NAME:-Docker Panel}"
    DEVICE_ID="docker_$(echo $DEVICE_NAME | tr '[:upper:]' '[:lower:]' | tr ' ' '_' | sed 's/[^a-z0-9_]//g')_$(date +%s)"
    
    cat > "$CONFIG_DIR/config.json" << EOF
{
  "url": "$HA_URL",
  "token": "$HA_TOKEN",
  "deviceName": "$DEVICE_NAME",
  "deviceId": "$DEVICE_ID",
  "webhookId": "",
  "registered": false,
  "fullscreen": true
}
EOF
    echo "[Entrypoint] Config created for $DEVICE_NAME → $HA_URL"
  else
    echo "[Entrypoint] Using existing config.json"
  fi
fi

# Symlink config dir
mkdir -p ~/.config
if [ ! -d ~/.config/ha-linux-companion ]; then
  ln -sf "$CONFIG_DIR" ~/.config/ha-linux-companion
fi

# Start Xvfb
echo "[Entrypoint] Starting Xvfb at ${RESOLUTION:-1280x720}..."
Xvfb :99 -screen 0 "${RESOLUTION:-1280x720}x24" &
XVFB_PID=$!
sleep 1

# Start x11vnc (no password)
echo "[Entrypoint] Starting x11vnc..."
x11vnc -display :99 -forever -nopw -rfbport 5900 -shared &
sleep 1

# Start noVNC/websockify
echo "[Entrypoint] Starting noVNC on port ${NOVNC_PORT:-8080}..."
websockify --web=/usr/share/novnc/ ${NOVNC_PORT:-8080} localhost:5900 &
WS_PID=$!
sleep 1

echo "============================================"
echo "  HA Linux Companion — Docker"
echo "  noVNC: http://localhost:${NOVNC_PORT:-8080}/vnc.html"
echo "  Resolution: ${RESOLUTION:-1280x720}"
echo "============================================"

# Start the app
echo "[Entrypoint] Starting HA Linux Companion..."
cd /app
exec npx electron . --no-sandbox --disable-gpu-sandbox --disable-dev-shm-usage 2>&1 | tee "$CONFIG_DIR/app.log"
