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

### 2. Environment Variables
Create a `.env` file in the root directory with the following keys:
```env
# Food Recognition (Clarifai)
FOOD_API_KEY=your_clarifai_key
MODEL_ID=your_model_id
FOOD_PROVIDER=auto
# Optional local model settings
# LOCAL_FOOD_MODEL_PATH=models/food/yolov8n-food101-cls.pt
# LOCAL_FOOD_MODEL_FALLBACK_PATH=yolov8n-cls.pt
# LOCAL_FOOD_TOPK=5
# LOCAL_FOOD_CONFIDENCE=0.08
# FOOD_MIN_CONFIDENCE=0.08
# FOOD_MIN_INTERVAL_S=2.5

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
- `FOOD_PROVIDER=auto` (default): local-first + API augmentation if key/model are present.
- no Clarifai key/model: runs fully local.
- `FOOD_PROVIDER=api`: prefer API when available, but still falls back to local if unavailable.
- local model path defaults to `models/food/yolov8n-food101-cls.pt` (food-specific).
- if that file is missing, it auto-falls back to `yolov8n-cls.pt`.

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
