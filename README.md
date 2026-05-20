# Cammy — AI child mealtime monitoring

WebRTC app: child presence, emotion, food detection, cough/sneeze alerts.

---

## Before you start

1. **Food model** (~329 MB) — not in git → [Google Drive](https://drive.google.com/drive/folders/1uq5ZYzULasSR8PRsG6s9EufrXfazgtdR?usp=sharing)  
   Save as: `models/food/food_detector.pt`

2. **MongoDB** on port 27017  
   `docker run -d -p 27017:27017 --name cammy-mongo mongo:7`

3. **`.env`** — `cp .env.example .env` and add keys (see `.env.example`)

4. **HTTPS certs** in project root: `cert.pem`, `key.pem`  
   `openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -days 365 -nodes -subj "/CN=localhost"`

---

## Ubuntu server (production)

Project path: `/home/user/cammy/Chillbaby_AI`

**First-time setup:**

```bash
cd /home/user/cammy/Chillbaby_AI
python3 -m venv venv
source /home/user/cammy/Chillbaby_AI/venv/bin/activate
pip install -r requirements.txt
# place food_detector.pt in models/food/ — see Google Drive link above
```

**Run server:**

```bash
cd /home/user/cammy/Chillbaby_AI
source /home/user/cammy/Chillbaby_AI/venv/bin/activate
python chillapp.py --cert-file cert.pem --key-file key.pem
```

**App URL:** https://159.223.225.25:5000/process

---

## Windows (local)

```powershell
.\bootstrap.ps1
.\run.ps1
```

Open: https://localhost:5000/process

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Database unavailable | Start MongoDB |
| Bad food detection | `food_detector.pt` must be ~329 MB from Drive, not a 134-byte git stub |
| `invalid load key, 'v'` | `rm yolov8m.pt yolov8n.pt` then `python -c "from ultralytics import YOLO; YOLO('yolov8m.pt')"` |

More: [`UBUNTU_SETUP.md`](UBUNTU_SETUP.md) · [`.env.example`](.env.example)
