# MealtimeCammy — AI child mealtime monitoring

WebRTC app: child presence, emotion, food detection, cough/sneeze alerts.

**Repository:** https://github.com/JasonLoweCBT/MealtimeCammy

---

## 1. Clone the project

```bash
git clone https://github.com/JasonLoweCBT/MealtimeCammy.git
cd MealtimeCammy
```

Ubuntu server example path: `/home/user/cammy/MealtimeCammy`

---

## 2. MongoDB

**Ubuntu**

```bash
sudo apt install -y mongodb-org
sudo systemctl start mongod
sudo systemctl enable mongod
sudo systemctl status mongod
```

`.env`: `DB_URL=mongodb://localhost:27017/`

**Windows**

1. Install [MongoDB Community Server](https://www.mongodb.com/try/download/community) (default port **27017**).
2. Start the service:
   - **Services** app → start **MongoDB Server**, or
   - **cmd (Admin):** `net start MongoDB`

Same `.env` line as Ubuntu.

---

## 3. Food model

Not in git. Download from [Google Drive](https://drive.google.com/drive/folders/1uq5ZYzULasSR8PRsG6s9EufrXfazgtdR?usp=sharing) → **`food_detector.pt`** (~329 MB)

```bash
mkdir -p models/food
# save file as:
models/food/food_detector.pt
```

Check size (~329 MB). A ~134-byte file is wrong (Git LFS stub).

---

## 4. Config and HTTPS

```bash
cp .env.example .env
# edit API keys — see .env.example
```

Certs in project root (one-time):

```bash
openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -days 365 -nodes -subj "/CN=localhost"
```

---

## 5. Ubuntu server — install and run

Path: `/home/user/cammy/MealtimeCammy` (if your server still has an older folder name `Chillbaby_AI`, use that path instead)

**First time:**

```bash
cd /home/user/cammy/MealtimeCammy
python3 -m venv venv
source /home/user/cammy/MealtimeCammy/venv/bin/activate
pip install -r requirements.txt
```

**Every run:**

```bash
cd /home/user/cammy/MealtimeCammy
source /home/user/cammy/MealtimeCammy/venv/bin/activate
python chillapp.py --cert-file cert.pem --key-file key.pem
```

**URL:** https://159.223.225.25:5000/process

---

## 6. Windows — install and run

```powershell
cd D:\path\to\MealtimeCammy
.\bootstrap.ps1
.\run.ps1
```

**URL:** https://localhost:5000/process

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Database unavailable | Ubuntu: `sudo systemctl start mongod` · Windows: start MongoDB service |
| Bad food detection | Re-download `food_detector.pt` from Drive (~329 MB) |
| `invalid load key, 'v'` | `rm yolov8m.pt yolov8n.pt` then download via Ultralytics (see `UBUNTU_SETUP.md`) |

[`UBUNTU_SETUP.md`](UBUNTU_SETUP.md) · [`.env.example`](.env.example)
