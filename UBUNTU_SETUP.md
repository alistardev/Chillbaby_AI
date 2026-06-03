# 🐧 Chill Baby AI — Ubuntu Setup Guide

> Tested on **Ubuntu 22.04 LTS**. Run all commands in your terminal unless stated otherwise.

---

## ✅ Prerequisites

Before starting, make sure you have:

- Ubuntu 22.04 (or 20.04) with internet access
- A domain or server IP (for HTTPS / WebRTC to work)
- Your `.env` file with API keys (FOOD_API_KEY, OPENAI_API_KEY, DB_URL, etc.)

---

## Step 1 — Update System & Install Dependencies

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y \
    python3 python3-pip python3-venv \
    ffmpeg \
    git \
    libgl1 libglib2.0-0 \
    portaudio19-dev
```

> **`libgl1` and `libglib2.0-0`** are required by OpenCV on headless Ubuntu servers.
> **`portaudio19-dev`** is required by `sounddevice` for audio capture.

---

## Step 2 — Install MongoDB

> **`sudo apt install mongodb-org` alone will fail** with `E: Unable to locate package mongodb-org` — Ubuntu’s default repos do not include it. Run **all** commands below first.

```bash
sudo apt install -y gnupg curl

# Import MongoDB GPG key
curl -fsSL https://www.mongodb.org/static/pgp/server-7.0.asc | \
  sudo gpg -o /usr/share/keyrings/mongodb-server-7.0.gpg --dearmor

# Add MongoDB repository
echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] \
  https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/7.0 multiverse" | \
  sudo tee /etc/apt/sources.list.d/mongodb-org-7.0.list

# Install MongoDB
sudo apt update && sudo apt install -y mongodb-org

# Start and enable MongoDB on boot
sudo systemctl start mongod
sudo systemctl enable mongod

# Verify it's running
sudo systemctl status mongod
mongosh --eval "db.runCommand({ ping: 1 })"
```

On **Ubuntu 24.04 (Noble)**, MongoDB still uses the **`jammy`** repo line above (no `noble` suite yet) — that is expected.

If a conflicting old package is installed: `sudo apt remove -y mongodb mongodb-server mongodb-clients` then reinstall `mongodb-org`.

---

## Step 3 — Clone the Repository

```bash
cd Chill-baby-
```

---

## Step 4 — Python version & virtual environment

**Required:** Python **3.10**, **3.11**, or **3.12** (not 3.13).

```bash
python3 --version
```

| `python3 --version` | What to do                                                                                                                                                                 |
| ------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 3.10.x or 3.11.x    | Create venv with `python3` (steps below)                                                                                                                                   |
| 3.12.x              | Use **current** `requirements.txt` from this repo (TensorFlow **≥2.16**). If `pip install` fails on `tensorflow<2.11`, you have an **old** requirements file — `git pull`. |
| 3.13+               | Install 3.10 or 3.12: `sudo apt install -y python3.10 python3.10-venv` then `python3.10 -m venv venv`                                                                      |

```bash
python3 -m venv venv
source venv/bin/activate
python --version   # must show 3.10 / 3.11 / 3.12
```

> You should now see `(venv)` at the start of your terminal prompt.  
> (`cammy` also works if you prefer that name — use the same folder in all following commands.)

**Windows / CTO local:** use `.\bootstrap.ps1` (bundled Python 3.10.20).

---

## Step 5 — Install Python Packages

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

> ⚠️ This may take **5–15 minutes** (TensorFlow, PyTorch, OpenCV, MediaPipe, FER, etc.).

**If you see** `No matching distribution found for tensorflow<2.11`:

- Cause: **Python 3.12** + old pinned TensorFlow 2.10 in `requirements.txt`.
- Fix: update the repo and reinstall, or use Python 3.10 venv (see table above).

---

## Step 6 — Set Up Environment Variables

Copy the **server** profile template:

```bash
cp .env.server.example .env
nano .env
```

Minimum — confirm these lines:

```env
CAMMY_PROFILE=server
DB_URL=mongodb://localhost:27017/
FOOD_API_KEY=your_clarifai_api_key
MODEL_ID=general-image-recognition
OPENAI_API_KEY=your_azure_openai_key
FOOD_PROVIDER=auto
```

`CAMMY_PROFILE=server` applies CPU-friendly defaults (smaller canvas, emotion interval 2s, FER without MTCNN, food boot delay). Override any single key in `.env` if needed.

On startup you should see: `Runtime profile: CAMMY_PROFILE=server (cuda=False) …`

Save with `Ctrl+O`, then `Ctrl+X`.

### Food model weights (required for good detection)

`models/food/food_detector.pt` is **not in git** (~329 MB).

**Option A — Google Drive (recommended for client / new machines):**

1. Download from [food — Google Drive](https://drive.google.com/drive/folders/1uq5ZYzULasSR8PRsG6s9EufrXfazgtdR?usp=sharing) → **`food_detector.pt`**
2. Place at `models/food/food_detector.pt` in the repo

**Option B — `scp` from a PC that already has the real file:**

```powershell
scp D:\work\Chillbaby_AI\models\food\food_detector.pt user@server:/path/to/Chillbaby_AI/models/food/
```

**Verify:**

```bash
ls -lh models/food/food_detector.pt
head -c 200 models/food/food_detector.pt
```

You want **~329 MB**. If you see **~134 bytes** and `version https://git-lfs.github.com`, that is a **Git LFS pointer**, not the model.

**Fix broken `yolov8m.pt` / `yolov8n.pt` stubs** (same LFS issue — `invalid load key, 'v'`):

```bash
cd /path/to/Chillbaby_AI
source venv/bin/activate
rm -f yolov8m.pt yolov8n.pt
python -c "from ultralytics import YOLO; YOLO('yolov8m.pt'); YOLO('yolov8n.pt')"
```

> If YOLO fails with **`libGL.so.1: cannot open shared object file`**, install Step 1 packages:  
> `sudo apt install -y libgl1 libglib2.0-0`

**Verify TensorFlow + FER** (after `pip install -r requirements.txt`):

```bash
source venv/bin/activate
python -c "import tensorflow; from fer.fer import FER; print('tensorflow', tensorflow.__version__); print('FER ok')"
```

Or match what the app uses:

```bash
python -c "from services.emotion import get_detector; d=get_detector(); print('FER', 'ready' if d else 'unavailable')"
```

Notes:

- **fer ≥ 25:** use `from fer.fer import FER` — `from fer import FER` fails even when the package is installed correctly.
- **TensorFlow logs** `Could not find cuda drivers` / `oneDNN` on a CPU VPS are **informational**, not install failures.

After placing the real `food_detector.pt`, **restart the app** (`source venv/bin/activate` then `python chillapp.py ...`).

---

## Step 7 — Generate SSL Certificates (HTTPS)

WebRTC **requires HTTPS**. Use one of the two options below:

### Option A — Self-signed (for testing/LAN use)

```bash
openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -days 365 -nodes \
  -subj "/CN=localhost"
```

### Option B — Let's Encrypt (for a real domain, recommended for production)

```bash
sudo apt install -y certbot
sudo certbot certonly --standalone -d yourdomain.com
# Then copy the certs:
sudo cp /etc/letsencrypt/live/yourdomain.com/fullchain.pem cert.pem
sudo cp /etc/letsencrypt/live/yourdomain.com/privkey.pem key.pem
sudo chown $USER:$USER cert.pem key.pem
```

---

## Step 8 — Create Videos Folder

```bash
mkdir -p static/videos
```

---

## Step 9 — Run the Application

```bash
bash start_ubuntu.sh
```

Or manually:

```bash
source venv/bin/activate
python chillapp.py --cert-file cert.pem --key-file key.pem --host 0.0.0.0 --port 5000
```

The server will start at:

```
https://<your-server-ip>:5000
```

Open that URL in your browser (Chrome or Edge recommended for WebRTC).

---

## Step 10 — Run as a Background Service (Optional, for Production)

To keep the app running after you close the terminal.

**Option A — copy the repo template** (paths default to `/root/Chillbaby_AI`):

```bash
cd ~/Chillbaby_AI
sudo cp deploy/chillbaby.service.example /etc/systemd/system/chillbaby.service
# If the app lives elsewhere, edit User, WorkingDirectory, and both paths in ExecStart:
sudo nano /etc/systemd/system/chillbaby.service
```

**Option B — create the file manually** — all paths must be **absolute** and must exist. Example for this VPS layout (`root`, repo in `~/Chillbaby_AI`):

```ini
[Unit]
Description=Chill Baby AI (MealtimeCammy)
After=network-online.target mongod.service
Wants=network-online.target

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=/root/Chillbaby_AI
Environment=PYTHONUNBUFFERED=1
ExecStart=/root/Chillbaby_AI/venv/bin/python /root/Chillbaby_AI/chillapp.py --cert-file cert.pem --key-file key.pem --host 0.0.0.0 --port 5000
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

> Do **not** leave `YOUR_USERNAME` in the file. Do **not** put `sudo` in `ExecStart`. Use Unix line endings (LF), not Windows CRLF.

Then enable it:

```bash
sudo systemctl daemon-reload
sudo systemd-analyze verify /etc/systemd/system/chillbaby.service
sudo systemctl enable chillbaby
sudo systemctl start chillbaby
sudo systemctl status chillbaby
journalctl -u chillbaby -n 50 --no-pager
```

---

## 🔍 Troubleshooting

| Problem                                   | Fix                                                                                                                 |
| ----------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| `E: Unable to locate package mongodb-org` | Add MongoDB apt repo (Step 2), then `sudo apt update`. Do not run `apt install mongodb-org` without the repo file.  |
| `ImportError: libGL.so.1`                 | `sudo apt install -y libgl1 libglib2.0-0` (Step 1). Required before Ultralytics/OpenCV import on headless servers.  |
| `cannot import name 'FER' from 'fer'`     | Use `from fer.fer import FER` (fer ≥ 25), or `from services.emotion import get_detector` — see Step 6 verify block. |
| TensorFlow: `Could not find cuda drivers` | Normal on CPU VPS; emotion/YOLO run on CPU. Use `CAMMY_PROFILE=server` in `.env`.                                   |
| `PortAudio not found`                     | `sudo apt install -y portaudio19-dev` then reinstall `sounddevice`                                                  |
| MongoDB not running                       | `sudo systemctl start mongod`                                                                                       |
| FFmpeg not found                          | `sudo apt install -y ffmpeg`                                                                                        |
| WebRTC fails / camera not shared          | Make sure you're on HTTPS (not HTTP)                                                                                |
| TensorFlow slow on first run              | YAMNet model is downloaded from TF Hub on first audio request — wait a minute                                       |
| Permission denied on `start_ubuntu.sh`    | `chmod +x start_ubuntu.sh`                                                                                          |
| `chillbaby.service has a bad unit file setting` | Run `sudo systemd-analyze verify /etc/systemd/system/chillbaby.service` — fix the line it names. Common causes: leftover `YOUR_USERNAME`, typo in a directive, `ExecStart` without full paths, or CRLF line endings from Windows. Replace with [`deploy/chillbaby.service.example`](deploy/chillbaby.service.example). |
| `Failed to determine user credentials` | `User=` must be a real system account (`root` or e.g. `ubuntu`). Match `WorkingDirectory` to that user’s home path. |

---

## 📁 Key Files Reference

| File                 | Purpose                                   |
| -------------------- | ----------------------------------------- |
| `chillapp.py`        | Main application entry point              |
| `config.py`          | App configuration & environment variables |
| `start_ubuntu.sh`    | Ubuntu startup script                     |
| `requirements.txt`   | Python dependencies                       |
| `.env`               | Secret API keys (never commit this!)      |
| `cert.pem / key.pem` | SSL certificates for HTTPS                |
| `static/videos/`     | Recorded session videos                   |
