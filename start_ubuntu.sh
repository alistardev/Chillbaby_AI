#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# start_ubuntu.sh  –  Chill Baby AI startup script for Ubuntu
#
# Usage:
#   bash start_ubuntu.sh
#
# Requirements (one-time setup):
#   sudo apt update && sudo apt install -y python3-venv python3-pip ffmpeg
#   python3 -m venv cammy
#   source cammy/bin/activate && pip install -r requirements.txt
# ─────────────────────────────────────────────────────────────────────────────

set -e   # exit immediately on any error

# 1. Activate the Python virtual environment (Linux path: bin/activate)
source cammy/bin/activate

# 2. Start MongoDB  (Ubuntu uses systemctl + service name 'mongod')
echo "[INFO] Starting MongoDB..."
sudo systemctl start mongod

# 3. Launch the application
echo "[INFO] Starting Chill Baby AI server..."
python chillapp.py --cert-file cert.pem --key-file key.pem
