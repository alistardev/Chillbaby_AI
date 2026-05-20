# Cammy - Advanced AI Child Monitoring System

Cammy is a modular, high-performance web application designed for real-time child monitoring during mealtimes. It leverages WebRTC for low-latency streaming and multiple AI models for emotion, food, and safety detection.

## 🚀 Key Features

### Phase 1: Modular Architecture & Async Database
- **Modular Design**: Refactored from a monolithic script into a clean, maintainable structure with dedicated `routes/` and `services/`.
- **Asynchronous Operations**: Uses `aiohttp` for the web server and `motor` for non-blocking MongoDB interactions.
- **Structured Logging**: Replaced all print statements with a robust Python `logging` configuration.

### Phase 2: Child Presence Detection (YOLOv8)
- **Safety Alerts**: Integrates YOLOv8 to detect if a child is present in the frame.
- **Real-time Notifications**: Triggers a "Child not detected" warning on the frontend and logs `child_missing` alerts to MongoDB when the child leaves the frame.

### Phase 3: Audio Sound Classification (PANNs CNN14)
- **Cough & Sneeze Detection**: Uses pretrained PANNs (`panns-inference`, AudioSet CNN14) for respiratory events.
- **Auto-dismissing Alerts**: Real-time WebSocket notifications with automatic dismissal after 5 seconds.

### Phase 4: Performance & Optimization
- **Background AI Inference**: Emotion detection (FER) and Child detection (YOLOv8) run in background thread executors to prevent video lag.
- **Scalable Configuration**: Centralized environment-based configuration in `config.py`.

## 🛠️ Tech Stack
- **Backend**: Python, aiohttp, aiortc, MongoDB (motor)
- **AI/ML**: PyTorch (PANNs / AudioSet tagging), TensorFlow (optional), Ultralytics (YOLOv8), FER (Emotion Detection), MediaPipe (Face Mesh)
- **Frontend**: Vanilla HTML5, CSS3, JavaScript (WebRTC, WebSockets)
- **APIs**: Clarifai (Food Recognition), Azure OpenAI (Nutrition Analysis)

## 📋 Setup Instructions

### 1. Prerequisites
- Python 3.10+
- MongoDB installed and running locally on port 27017.

If login shows **“Database unavailable”** or logs show **`WinError 10061` / `actively refused` on `localhost:27017`**, MongoDB is not running. Examples:

- **Windows service:** `net start MongoDB` (service name may vary; check *Services* for “MongoDB”).
- **Manual:** run `mongod` with your config so it listens on `27017`.
- **Docker:** `docker run -d -p 27017:27017 --name cammy-mongo mongo:7`

### 2. Environment Variables
Create a `.env` file in the root directory with the following keys:
```env
# Food Recognition (Clarifai — optional; default is local-only YOLO)
FOOD_API_KEY=your_clarifai_key
MODEL_ID=your_model_id
FOOD_PROVIDER=local
# Local food detection (YOLO .pt — see models/food/README.md)
# LOCAL_FOOD_MODEL_PATH=models/food/food_detector.pt
# LOCAL_FOOD_MODEL_FALLBACK_PATH=
# LOCAL_FOOD_CONFIDENCE=0.25
# LOCAL_FOOD_IOU=0.7
# FOOD_MIN_CONFIDENCE=0.08
# FOOD_MIN_INTERVAL_S=1.0
# LOCAL_FOOD_COCO_ALWAYS_MERGE=0   # faster: second YOLO only when custom model is weak
# LOCAL_FOOD_DEVICE=               # empty = auto CUDA/CPU

# Nutrition Analysis (Azure OpenAI)
OPENAI_API_KEY=your_openai_key

# Database
DB_URL=mongodb://localhost:27017/

# Audio performance tuning (optional)
# PANN_HOP_FRACTION=0.60
# PANN_QUEUE_MAXSIZE=12
# PANN_QUEUE_HIGH_WATERMARK=0.7
```

Food provider behavior:
- **`FOOD_PROVIDER=local`**: **only** local YOLO (+ COCO merge if `LOCAL_FOOD_COCO_ALWAYS_MERGE=1`). No Clarifai — saves API credits.
- **`FOOD_PROVIDER=auto`** (recommended for client demos): custom `food_detector.pt` **plus** COCO `yolov8m` on every frame (`LOCAL_FOOD_COCO_ALWAYS_MERGE=1`) **plus** Clarifai merged every ~3s (`CLARIFAI_MERGE_EVERY_FRAME=1`) — same strategy as the cammy fork (hand-held and desk food).
- Set `CLARIFAI_MERGE_EVERY_FRAME=0` and `CLARIFAI_MIN_INTERVAL_S=45` to restore credit-saving fallback-only Clarifai.
- Set `CLARIFAI_FALLBACK_ONLY=0` only if you intentionally want Clarifai on every food frame (not recommended for free keys).
- Local primary: **`models/food/food_detector.pt`**. If it finds nothing, **`yolov8m.pt`** COCO food classes (apple, banana, …) can fill in when `LOCAL_FOOD_COCO_MERGE_ON_MISS=1`.
- **Full frame only** — no percentage crops; child and food are detected wherever they appear in view (child on WebRTC ~540px path with person ROI for FER; food on canvas JPEG).
- **`STREAM_FOOD_FROM_VIDEO=0`** (default): food runs from the browser **canvas** every ~3s (one YOLO pass — keeps CPU low). Set **`1`** only if you need server-side food without canvas (duplicates work).
- **`FOOD_CANVAS_MAX_DIM`** (default `960`): scales down full-frame JPEGs before upload; raise slightly if food is small in frame.
- Clarifai demo: `MODEL_ID=general-image-recognition`, `CLARIFAI_MIN_CONFIDENCE=0.75`.

Nutrition UI uses **`nutrition_score.js`**. WebSocket **`_state` 5** sends `nutrition` + `result`.

- **`NUTRITION_PROVIDER=auto`** (default): Azure when `OPENAI_API_KEY` is set; otherwise **`data/nutrition_lookup.json`** (offline estimates by food name substring).
- **`local`**: JSON only. **`none`**: no nutrition messages.

Food weights: with **`CAMMY_AUTO_SYNC_FOOD_MODEL=1`**, missing **`models/food/food_detector.pt`** is filled from `prepare_food_dataset/` on server start, or run **`scripts/sync_food_model.ps1`**.

### 3. Installation (Windows move-safe)
Use the project bootstrap script instead of reusing a moved `venv`:
```powershell
.\bootstrap.ps1
```

This always creates/uses `.\venv` in the current folder, so moving the repository does not keep stale interpreter paths.

The first time you run cough/sneeze detection, PANNs downloads **class labels** and the **CNN14 weights** (~330 MB) into a `panns_data` folder under your user home directory. Ensure disk space and network access.

### 4. SSL Certificates (Required for WebRTC)
Generate self-signed certificates for local testing:
```bash
openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -days 365 -nodes -subj "/CN=localhost"
```

### 5. Running the Application
```powershell
.\run.ps1
```

You can still run manually if needed:
```powershell
.\venv\Scripts\python.exe chillapp.py --cert-file cert.pem --key-file key.pem
```
Access the app at `https://localhost:5000`.

### 6. Development Hot Reload
For local development, use the hot-reload script:
```powershell
.\dev.ps1
```

Optional parameters:
```powershell
.\dev.ps1 -HostName 0.0.0.0 -Port 5000 -CertFile cert.pem -KeyFile key.pem
```

Notes:
- The script auto-installs `watchfiles` in `venv` if missing.
- It sets `CAMMY_SKIP_PANN_WARMUP=1` to reduce restart time.
- Stop with `Ctrl + C`.

## 📂 Project Structure
- `chillapp.py`: Application entry point.
- `routes/`: API and WebSocket route handlers.
- `services/`: AI logic and external service integrations.
- `static/`: Frontend assets (CSS, JS, images).
- `templates/`: HTML templates.
- `config.py`: Centralized configuration.
- `db.py`: Database client setup.
