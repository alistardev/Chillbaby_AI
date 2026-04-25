import os
import sys
import shutil
from dotenv import load_dotenv

load_dotenv()

# ── Clarifai food recognition ───────────────────────────────────────────────
FOOD_API_KEY = os.getenv('FOOD_API_KEY', '')
MODEL_ID     = os.getenv('MODEL_ID', '')

# ── Azure OpenAI ─────────────────────────────────────────────────────────────
OPENAI_API_KEY     = os.getenv('OPENAI_API_KEY', '')
OPENAI_API_BASE    = "https://babii.openai.azure.com/"
OPENAI_API_VERSION = "2023-07-01-preview"
OPENAI_ENGINE      = "babii-chat-gpt-4-32"

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
FOOD_CAPTURE_INTERVAL_S = 3    # seconds between canvas food snapshots (frontend)

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
YOLO_MODEL_PATH         = 'yolov8n.pt'   # auto-downloaded on first run (~6 MB)
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
PANN_HOP_FRACTION      = 0.38
PANN_HOP_SAMPLES       = max(
    2000,
    int(PANN_CHUNK_SAMPLES * PANN_HOP_FRACTION),
)

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
