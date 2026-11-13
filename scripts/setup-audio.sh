#!/bin/bash
# HA Linux Companion — Audio Setup for Raspberry Pi OS Lite
# Installs PipeWire for proper audio mixing (squeezelite + notifications)
# Safe to run on any Debian-based system

set -e

echo "=== HA Linux Companion — Audio Setup ==="
echo ""

# Check if we're on a Debian-based system
if ! command -v apt-get &>/dev/null; then
  echo "ERROR: This script requires apt-get (Debian/Ubuntu/Raspbian)"
  exit 1
fi

# Check if PipeWire is already running
if pactl info 2>/dev/null | grep -q "PipeWire"; then
  echo "✓ PipeWire is already running. Nothing to do."
  exit 0
fi

if pactl info 2>/dev/null | grep -q "PulseAudio"; then
  echo "✓ PulseAudio is already running. Nothing to do."
  exit 0
fi

echo "Installing PipeWire audio server..."
echo "This enables multiple apps to share the audio device simultaneously."
echo ""

sudo apt-get update -qq
sudo apt-get install -y -qq \
  pipewire \
  pipewire-alsa \
  wireplumber \
  pipewire-pulse \
  libspa-0.2-bluetooth \
  2>/dev/null

# Start PipeWire for current session
systemctl --user daemon-reload 2>/dev/null || true
systemctl --user enable --now pipewire wireplumber pipewire-pulse 2>/dev/null || {
  # Fallback for systems without user lingering
  echo "Starting PipeWire manually..."
  pipewire &
  sleep 1
  wireplumber &
  sleep 1
  pipewire -c pipewire-pulse.conf &
  sleep 1
}

# Verify
if pactl info 2>/dev/null | grep -q "PipeWire"; then
  echo ""
  echo "✓ PipeWire installed and running!"
  echo ""
  echo "NOTE: If squeezelite is installed, update its config to use ALSA default:"
  echo "  squeezelite -o default ..."
  echo ""
  echo "This lets both squeezelite and HA Companion notifications play audio."
else
  echo ""
  echo "⚠ PipeWire installed but not yet active."
  echo "Reboot the system to activate: sudo reboot"
fi
