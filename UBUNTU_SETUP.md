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

```bash
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
```

---

## Step 3 — Clone the Repository

```bash
cd Chill-baby-
```

---

## Step 4 — Create Python Virtual Environment

```bash
python3 -m venv cammy
source cammy/bin/activate
```

> You should now see `(cammy)` at the start of your terminal prompt.

---

## Step 5 — Install Python Packages

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

> ⚠️ This may take **5–10 minutes** as it installs TensorFlow, PyTorch, OpenCV, MediaPipe, etc.

---

## Step 6 — Set Up Environment Variables

Create a `.env` file in the project root:

```bash
nano .env
```

Paste and fill in your keys:

```env
FOOD_API_KEY=your_clarifai_api_key
MODEL_ID=your_clarifai_model_id
OPENAI_API_KEY=your_azure_openai_key
FOODVISOR_API=your_foodvisor_api_key
DB_URL=mongodb://localhost:27017/
```

Save with `Ctrl+O`, then `Ctrl+X`.

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
source cammy/bin/activate
python chillapp.py --cert-file cert.pem --key-file key.pem
```

The server will start at:
```
https://<your-server-ip>:5000
```

Open that URL in your browser (Chrome or Edge recommended for WebRTC).

---

## Step 10 — Run as a Background Service (Optional, for Production)

To keep the app running after you close the terminal:

```bash
sudo nano /etc/systemd/system/chillbaby.service
```

Paste the following (update paths to match your setup):

```ini
[Unit]
Description=Chill Baby AI Server
After=network.target mongod.service

[Service]
User=YOUR_USERNAME
WorkingDirectory=/home/YOUR_USERNAME/Chill-baby-
ExecStart=/home/YOUR_USERNAME/Chill-baby-/cammy/bin/python chillapp.py --cert-file cert.pem --key-file key.pem
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Then enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable chillbaby
sudo systemctl start chillbaby
sudo systemctl status chillbaby
```

---

## 🔍 Troubleshooting

| Problem | Fix |
|---|---|
| `ImportError: libGL.so.1` | `sudo apt install -y libgl1` |
| `PortAudio not found` | `sudo apt install -y portaudio19-dev` then reinstall `sounddevice` |
| MongoDB not running | `sudo systemctl start mongod` |
| FFmpeg not found | `sudo apt install -y ffmpeg` |
| WebRTC fails / camera not shared | Make sure you're on HTTPS (not HTTP) |
| TensorFlow slow on first run | YAMNet model is downloaded from TF Hub on first audio request — wait a minute |
| Permission denied on `start_ubuntu.sh` | `chmod +x start_ubuntu.sh` |

---

## 📁 Key Files Reference

| File | Purpose |
|---|---|
| `chillapp.py` | Main application entry point |
| `config.py` | App configuration & environment variables |
| `start_ubuntu.sh` | Ubuntu startup script |
| `requirements.txt` | Python dependencies |
| `.env` | Secret API keys (never commit this!) |
| `cert.pem / key.pem` | SSL certificates for HTTPS |
| `static/videos/` | Recorded session videos |
