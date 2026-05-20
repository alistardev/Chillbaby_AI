import os
import sys
import shutil
from dotenv import load_dotenv

load_dotenv()

# Project root (directory containing this config file) — anchor relative paths here, not CWD.
_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))


def resolve_repo_path(path: str) -> str:
    """Turn repo-relative paths into absolute paths so the app works from any working directory."""
    p = (path or "").strip()
    if not p:
        return p
    if os.path.isabs(p):
        return os.path.normpath(p)
    return os.path.normpath(os.path.join(_REPO_ROOT, p.replace("/", os.sep)))


# ── Clarifai food recognition ───────────────────────────────────────────────
FOOD_API_KEY = os.getenv('FOOD_API_KEY', '')
FOOD_API_KEY_2 = os.getenv('FOOD_API_KEY_2', '')
MODEL_ID = os.getenv('MODEL_ID', 'general-image-recognition')
MODEL_VERSION_ID = os.getenv('MODEL_VERSION_ID', '').strip()
# local = YOLO only (default, saves Clarifai credits).
# auto = local always; Clarifai only when local is empty/weak (see CLARIFAI_FALLBACK_ONLY).
# api  = Clarifai when keys exist, but still runs local first unless CLARIFAI_ONLY=1.
FOOD_PROVIDER = os.getenv("FOOD_PROVIDER", "local").strip().lower()
CLARIFAI_USER_ID = os.getenv("CLARIFAI_USER_ID", "clarifai")
CLARIFAI_APP_ID = os.getenv("CLARIFAI_APP_ID", "main")
CLARIFAI_MIN_CONFIDENCE = float(os.getenv("CLARIFAI_MIN_CONFIDENCE", "0.55"))
# 1 (default): call Clarifai only if local YOLO did not produce a confident label.
CLARIFAI_FALLBACK_ONLY = os.getenv("CLARIFAI_FALLBACK_ONLY", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
# Skip Clarifai when local best score is already at or above this (matches FOOD_MIN_CONFIDENCE by default).
# Skip Clarifai when local best score is at/above this (pizza 0.9 → faster UI update).
CLARIFAI_SKIP_IF_LOCAL_CONF = float(os.getenv("CLARIFAI_SKIP_IF_LOCAL_CONF", "0.40"))
# Minimum seconds between Clarifai calls per session user (free-tier credit protection).
# Default 3s to align with canvas food snapshots (~cammy: Clarifai every frame).
CLARIFAI_MIN_INTERVAL_S = float(os.getenv("CLARIFAI_MIN_INTERVAL_S", "3.0"))
# 1 (default for auto/hybrid): merge Clarifai on every food frame (cammy behavior).
# 0: Clarifai only when local YOLO is empty/weak (credit-saving mode).
CLARIFAI_MERGE_EVERY_FRAME = os.getenv("CLARIFAI_MERGE_EVERY_FRAME", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)

# ── Azure OpenAI ─────────────────────────────────────────────────────────────
OPENAI_API_KEY     = os.getenv('OPENAI_API_KEY', '')
OPENAI_API_BASE    = "https://babii.openai.azure.com/"
OPENAI_API_VERSION = "2023-07-01-preview"
OPENAI_ENGINE      = "babii-chat-gpt-4-32"

# Nutrition: auto = Azure when OPENAI_API_KEY set, else local JSON lookup; azure | local | none
NUTRITION_PROVIDER = os.getenv("NUTRITION_PROVIDER", "auto").strip().lower()
NUTRITION_LOOKUP_JSON = os.getenv(
    "NUTRITION_LOOKUP_JSON",
    os.path.join(os.path.dirname(__file__), "data", "nutrition_lookup.json"),
)

# If 1 (default): when LOCAL_FOOD_MODEL_PATH is missing, copy from prepare_food_dataset/ if present
CAMMY_AUTO_SYNC_FOOD_MODEL = os.getenv("CAMMY_AUTO_SYNC_FOOD_MODEL", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)

# ── Foodvisor (defined but not actively used yet) ────────────────────────────
FOODVISOR_API = os.getenv('FOODVISOR_API', '')
FOODVISOR_URL = "https://vision.foodvisor.io/api/1.0/en/analysis"

# ── MongoDB ──────────────────────────────────────────────────────────────────
DB_URL  = os.getenv('DB_URL', 'mongodb://localhost:27017/')
DB_NAME = "mealtimecammy"

# ── Eye / Sleep detection thresholds ─────────────────────────────────────────
EYE_AR_THRESH       = 0.15
EYE_AR_CONSEC_FRAMES = 40

# ── Video processing ─────────────────────────────────────────────────────────
FRAME_RESIZE_WIDTH = 540        # resize all incoming frames to this width
EMOTION_EVERY_N_FRAMES = 30    # run FER every N WebRTC frames
# Seconds between browser canvas snapshots → /canvasImage (min 0.5 in frontend).
FOOD_CAPTURE_INTERVAL_S = max(0.5, float(os.getenv("FOOD_CAPTURE_INTERVAL_S", "1.5")))

# Local-first food detection — Ultralytics **detection** checkpoint (.pt), e.g.
# exported `food_detector.pt` or `best.pt` from your training run (see models/food/README.md).
# Paths are resolved relative to the repo root (folder containing config.py), not the shell CWD.
_raw_food_path = os.getenv("LOCAL_FOOD_MODEL_PATH", "models/food/food_detector.pt")
LOCAL_FOOD_MODEL_PATH = resolve_repo_path(_raw_food_path)
_fb = os.getenv("LOCAL_FOOD_MODEL_FALLBACK_PATH", "").strip()
LOCAL_FOOD_MODEL_FALLBACK_PATH = resolve_repo_path(_fb) if _fb else ""
LOCAL_FOOD_IOU = float(os.getenv("LOCAL_FOOD_IOU", "0.7"))
# Custom food_detector.pt per-box gate.
# Custom food_detector.pt — allow weak boxes (logs showed egg 0.08, beer 0.11 filtered at 0.12).
LOCAL_FOOD_CONFIDENCE = float(os.getenv("LOCAL_FOOD_CONFIDENCE", "0.08"))
# COCO yolov8m fallback gate (apple, banana, …).
LOCAL_FOOD_COCO_CONFIDENCE = float(os.getenv("LOCAL_FOOD_COCO_CONFIDENCE", "0.25"))
# Ultralytics predict conf for COCO pass (lower = more candidates, e.g. apple beside sandwich).
LOCAL_FOOD_COCO_PREDICT_CONF = float(os.getenv("LOCAL_FOOD_COCO_PREDICT_CONF", "0.25"))
# If custom food_detector.pt best score is at/above this, skip the extra COCO pass (faster UI on CPU).
LOCAL_FOOD_TRUST_CUSTOM = float(os.getenv("LOCAL_FOOD_TRUST_CUSTOM", "0.35"))
# cuda device index, "cpu", or empty = auto (CUDA if available else cpu).
LOCAL_FOOD_DEVICE = os.getenv("LOCAL_FOOD_DEVICE", "").strip()
_coco_fb = os.getenv("LOCAL_FOOD_COCO_FALLBACK_PATH", "yolov8m.pt").strip()
LOCAL_FOOD_COCO_FALLBACK_PATH = resolve_repo_path(_coco_fb) if _coco_fb else ""
LOCAL_FOOD_COCO_MERGE_ON_MISS = os.getenv("LOCAL_FOOD_COCO_MERGE_ON_MISS", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
# 1: always run COCO yolov8m (slower). 0 (default): COCO only when custom is weak/empty.
LOCAL_FOOD_COCO_ALWAYS_MERGE = os.getenv("LOCAL_FOOD_COCO_ALWAYS_MERGE", "0").strip().lower() not in (
    "0",
    "false",
    "no",
)
LOCAL_FOOD_CLS_CONFIDENCE = float(os.getenv("LOCAL_FOOD_CLS_CONFIDENCE", "0.12"))
LOCAL_FOOD_TOPK = int(os.getenv("LOCAL_FOOD_TOPK", "5"))
# 512 default — faster on CPU; raise to 640+ if accuracy drops.
LOCAL_FOOD_PREDICT_IMGSZ = max(320, min(1280, int(os.getenv("LOCAL_FOOD_PREDICT_IMGSZ", "512"))))
LOCAL_FOOD_UPSCALE_MAX_DIM = max(480, min(1280, int(os.getenv("LOCAL_FOOD_UPSCALE_MAX_DIM", "720"))))
FOOD_MIN_CONFIDENCE = float(os.getenv("FOOD_MIN_CONFIDENCE", "0.08"))
# Min seconds between duplicate food WS updates (same label); changes emit immediately.
FOOD_MIN_INTERVAL_S = float(os.getenv("FOOD_MIN_INTERVAL_S", "1.0"))
FOOD_CLEAR_DEBOUNCE_S = float(os.getenv("FOOD_CLEAR_DEBOUNCE_S", "1.0"))
# Browser canvas JPEG (full frame) — off by default; WebRTC food duplicates YOLO and slows the PC.
STREAM_FOOD_FROM_VIDEO = os.getenv("STREAM_FOOD_FROM_VIDEO", "0").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
FOOD_WEBRTC_MAX_WIDTH = int(os.getenv("FOOD_WEBRTC_MAX_WIDTH", "960"))
# Max long edge for canvas snapshots before POST /canvasImage (full frame, no crops).
FOOD_CANVAS_MAX_DIM = max(480, min(1920, int(os.getenv("FOOD_CANVAS_MAX_DIM", "720"))))

# ── Recording ────────────────────────────────────────────────────────────────
STATIC_VIDEO_FOLDER = './static/videos/'

# ── FFmpeg – cross-platform path resolver ────────────────────────────────────
def _resolve_ffmpeg() -> str:
    """Return the best available ffmpeg executable path for the current OS.

    Priority:
      1. Windows → bundled ffmpeg/ffmpeg.exe
      2. Linux/Mac → bundled ffmpeg/ffmpeg (if present and executable)
      3. Linux/Mac → system ffmpeg found on $PATH via shutil.which
      4. Fallback  → bare 'ffmpeg' (lets subprocess give a clear error)
    """
    if sys.platform == "win32":
        return os.path.join("ffmpeg", "ffmpeg.exe")
    # Linux / macOS – check for a locally bundled static binary first
    local = os.path.join("ffmpeg", "ffmpeg")
    if os.path.isfile(local) and os.access(local, os.X_OK):
        return local
    # Fall back to system-installed ffmpeg (e.g. installed via apt on Ubuntu)
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg
    return "ffmpeg"  # last resort – subprocess will raise FileNotFoundError

FFMPEG_PATH = _resolve_ffmpeg()

# ── Phase 2: YOLOv8 Child Detection ──────────────────────────────────────────
YOLO_MODEL_PATH         = resolve_repo_path(os.getenv("YOLO_MODEL_PATH", "yolov8n.pt"))
YOLO_DETECT_EVERY_N     = 15             # run detection every N WebRTC frames
YOLO_CONFIDENCE_THRESH  = 0.50           # minimum confidence to count as detected
YOLO_PERSON_CLASS_ID    = 0              # COCO class 0 = person

# ── Phase 3: PANNs CNN14 respiratory (cough / sneeze / wheeze / throat clear) ─
# panns-inference AudioTagging — AudioSet clipwise sigmoid scores (527 classes).
PANN_SAMPLE_RATE       = 32000             # CNN14 training rate
PANN_CHUNK_SECONDS     = 1.0             # clip length for tagging (seconds)
PANN_CHUNK_SAMPLES     = int(PANN_SAMPLE_RATE * PANN_CHUNK_SECONDS)

# Sliding window: after each inference, drop only this many samples (not the full
# chunk). Lower gap between windows → catches rapid coughs / sneezes. 0.38 ≈ 380 ms hop.
# Raise toward 1.0 if CPU is too high.
PANN_HOP_FRACTION      = float(os.getenv("PANN_HOP_FRACTION", "0.60"))
PANN_HOP_SAMPLES       = max(
    2000,
    int(PANN_CHUNK_SAMPLES * PANN_HOP_FRACTION),
)
PANN_QUEUE_MAXSIZE = int(os.getenv("PANN_QUEUE_MAXSIZE", "12"))
PANN_QUEUE_HIGH_WATERMARK = float(os.getenv("PANN_QUEUE_HIGH_WATERMARK", "0.7"))

# Clipwise score gates (sigmoid 0–1; tune on your mic/WebRTC levels)
PANN_SCORE_THRESHOLD   = 0.070           # softer gate — helps quiet / far-mic sneezes
PANN_MODERATE_SCORE    = 0.24
PANN_SEVERE_SCORE      = 0.45

# Linear gain on WebRTC audio before PANNs (farther mic). Clipped to [-1, 1] in audio_track.
PANN_INPUT_GAIN = float(os.getenv("PANN_INPUT_GAIN", "1.42"))

# Per 1 s window: if peak is very low (far mic), gently lift toward target before PANNs.
# Reduces need to sneeze “on top of” the mic. Set gate 0 to disable.
PANN_WINDOW_PEAK_GATE = float(os.getenv("PANN_WINDOW_PEAK_GATE", "0.065"))
PANN_WINDOW_PEAK_TARGET = float(os.getenv("PANN_WINDOW_PEAK_TARGET", "0.32"))

# Sneeze often loses argmax to "Cough" on the same burst; promote sneeze when strong
# enough and within this margin of the global respiratory max (wheeze/cough/throat/sneeze).
PANN_SNEEZE_PROMOTE_MIN   = 0.022
PANN_SNEEZE_NEAR_WINNER   = 0.11

# When argmax is "Cough" or "Wheeze" but "Sneeze" is close, CNN14 often mis-tags
# real sneezes (explosive burst reads as wheeze or cough).
PANN_SNEEZE_COUGH_TIE_BIAS  = 0.14
PANN_SNEEZE_WHEEZE_TIE_BIAS = 0.14

# Argmax "Throat clearing" vs sneeze confusion on short bursts
PANN_SNEEZE_THROAT_TIE_BIAS = 0.095

# Cough barely beats sneeze on argmax — common for soft/far sneezes
PANN_SNEEZE_RUNNER_MIN = 0.020
PANN_SNEEZE_RUNNER_MARGIN = 0.038

# Far mic: every respiratory logit is low, but sneeze tracks the peak — nudge combined so the
# gate still opens without flooding cough-only noise (requires sneeze near global resp max).
PANN_SNEEZE_QUIET_MIN = 0.024
PANN_SNEEZE_QUIET_GAP = 0.088
PANN_SNEEZE_QUIET_COMBINED_MULT = 2.05

# Even weaker sneeze logit but still competitive with resp peak (very quiet rooms)
PANN_SNEEZE_ULTRA_MIN = 0.017
PANN_SNEEZE_ULTRA_GAP = 0.105
PANN_SNEEZE_ULTRA_MULT = 2.28

# Rolling window for paroxysmal boost (events per minute → severity bump)
COUGH_BURST_WINDOW_SEC = 3.0
