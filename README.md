# MealtimeCammy

MealtimeCammy is an AI-powered child mealtime monitoring web app. It uses WebRTC for live video streaming and AI models for child presence, emotion, food, and cough/sneeze detection.

**Repository:** https://github.com/JasonLoweCBT/MealtimeCammy

---

## Features

- Live camera monitoring with WebRTC
- Child presence detection with YOLOv8
- Emotion detection
- Food detection
- Cough and sneeze audio alerts
- Real-time frontend alerts with WebSockets
- MongoDB alert logging

---

## Tech Stack

- **Backend:** Python, aiohttp, aiortc
- **Database:** MongoDB, motor
- **AI/ML:** YOLOv8, FER, MediaPipe, PANNs CNN14, PyTorch
- **Frontend:** HTML, CSS, JavaScript
- **External APIs:** Clarifai, Azure OpenAI

---

## Requirements

- Python 3.10+
- MongoDB on port `27017`
- `cert.pem` and `key.pem` (HTTPS / WebRTC)
- Model files below (**not in git** — download manually)

---

## Installation

### 1. Clone the project

```bash
git clone https://github.com/JasonLoweCBT/MealtimeCammy.git
cd MealtimeCammy
```

### 2. MongoDB

**Ubuntu**

```bash
sudo apt install -y mongodb-org
sudo systemctl start mongod
sudo systemctl enable mongod
sudo systemctl status mongod
```

**Windows** — install [MongoDB Community Server](https://www.mongodb.com/try/download/community), then start the **MongoDB Server** service (or `net start MongoDB`).

`.env`: `DB_URL=mongodb://localhost:27017/`

### 3. Install dependencies

**Ubuntu**

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**Windows**

```powershell
.\bootstrap.ps1
```

### 4. Configure environment

```bash
cp .env.example .env
```

Edit `.env` (minimum):

```env
FOOD_API_KEY=your_clarifai_key
MODEL_ID=general-image-recognition
OPENAI_API_KEY=your_openai_key
DB_URL=mongodb://localhost:27017/
FOOD_PROVIDER=auto
```

### 5. Download model files (manual)

All weights are **gitignored**. Copy them into the repo **before** running the app.

| File | Where to put it | Size (approx.) | Used for |
|------|-----------------|----------------|----------|
| **`food_detector.pt`** | `MealtimeCammy/models/food/food_detector.pt` | ~329 MB | Main food detection |
| **`yolov8m.pt`** | project root (`MealtimeCammy/yolov8m.pt`) | ~50 MB | COCO food fallback (apple, pizza, …) |
| **`yolov8n.pt`** | project root (`MealtimeCammy/yolov8n.pt`) | ~6 MB | Child / person detection |

Download link: [Google Drive](https://drive.google.com/drive/folders/1wmncu96q2wC7WSU6zBIM8kBF5n52N4jj)  


```bash
mkdir -p models/food
# save as models/food/food_detector.pt
```

**`yolov8m.pt` and `yolov8n.pt`** — alternative download from Ultralytics (one-time, with network):

```bash
# from repo root, with venv active:
python -c "from ultralytics import YOLO; YOLO('yolov8m.pt'); YOLO('yolov8n.pt')"
```


### 6. SSL certificates

```bash
openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -days 365 -nodes -subj "/CN=localhost"
```

---

## Running the app

**Ubuntu server** (example path: `/home/user/cammy/MealtimeCammy`)

```bash
cd /home/user/cammy/MealtimeCammy
source /home/user/cammy/MealtimeCammy/venv/bin/activate
python chillapp.py --cert-file cert.pem --key-file key.pem
```

**URL:** https://159.223.225.25:5000/process

**Windows** (local)

```powershell
cd D:\path\to\MealtimeCammy
.\run.ps1
```

**URL:** https://localhost:5000/process

**Dashboard (Phase 7):** https://localhost:5000/dashboard — meal history, food diary, allergen logs, child status (also linked via 📊 on the monitor page).

---

## Project structure

```text
chillapp.py
models/food/food_detector.pt   # custom food model
yolov8m.pt                     # COCO food (repo root)
yolov8n.pt                     # person detection (repo root)
routes/
services/
static/
templates/
```

---

## Notes

- MongoDB must be running before login works.
- PANNs may download ~330 MB of audio weights on first cough/sneeze detection.
- Only **`yolov8m.pt`** and **`yolov8n.pt`** belong in the repo root — not `yolov8n-cls.pt`.

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Food label slow on server | CPU YOLO ~2s is normal under load. Set `LOCAL_FOOD_PREDICT_IMGSZ=384`, `FOOD_CANVAS_MAX_DIM=640`, `FOOD_CAPTURE_INTERVAL_S=0.8`, `CAMMY_SKIP_PANN_WARMUP=1`; restart app |
| WebRTC alert on first connect | Harmless race (fixed in latest `detail.js`); hard-refresh `/process` if you still see it |
| Food model error | Re-download `food_detector.pt` (~329 MB) into `models/food/` |
| `invalid load key, 'v'` | Delete bad `.pt` stubs, re-download (section 5) |
| Clarifai-only food labels | Check `food_detector.pt` size and path |

[`UBUNTU_SETUP.md`](UBUNTU_SETUP.md) · [`.env.example`](.env.example)
