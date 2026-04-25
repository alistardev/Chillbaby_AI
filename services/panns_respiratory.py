"""
services/panns_respiratory.py

PANNs (CNN14) respiratory event detection via panns-inference — AudioSet 527 classes,
same ontology as audioset_tagging_cnn (better clipwise tagging than YAMNet for many events).

Requires: pip install panns-inference  (PyTorch; checkpoint downloaded on first run)
"""

from __future__ import annotations

import logging
import os
import threading
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np

from config import (
    PANN_CHUNK_SAMPLES,
    PANN_MODERATE_SCORE,
    PANN_SAMPLE_RATE,
    PANN_SCORE_THRESHOLD,
    PANN_SEVERE_SCORE,
    PANN_SNEEZE_COUGH_TIE_BIAS,
    PANN_SNEEZE_NEAR_WINNER,
    PANN_SNEEZE_PROMOTE_MIN,
    PANN_SNEEZE_QUIET_COMBINED_MULT,
    PANN_SNEEZE_QUIET_GAP,
    PANN_SNEEZE_QUIET_MIN,
    PANN_SNEEZE_RUNNER_MARGIN,
    PANN_SNEEZE_RUNNER_MIN,
    PANN_SNEEZE_THROAT_TIE_BIAS,
    PANN_SNEEZE_ULTRA_GAP,
    PANN_SNEEZE_ULTRA_MIN,
    PANN_SNEEZE_ULTRA_MULT,
    PANN_SNEEZE_WHEEZE_TIE_BIAS,
)

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_at_model: Any = None

# AudioSet indices (527 classes, class_labels_indices.csv order — matches PANNs labels[])
RESPIRATORY_INDICES = (
    42,  # Wheeze
    47,  # Cough
    48,  # Throat clearing
    49,  # Sneeze
)
# Speech / vocal sounds that compete with respiratory (indices 0–40; excludes breathing 41–50 band)
SPEECH_INDICES = tuple(range(41))


def _default_checkpoint_path() -> str:
    return str(Path.home() / "panns_data" / "Cnn14_mAP=0.431.pth")


def _ensure_panns_assets(checkpoint_path: str) -> None:
    """
    Download label CSV + CNN14 weights before importing panns_inference.

    The package's config.py uses wget on import if files are missing; Windows often
    has no wget, so we fetch the same URLs with urllib first.
    """
    pann_dir = Path.home() / "panns_data"
    pann_dir.mkdir(parents=True, exist_ok=True)

    labels_path = pann_dir / "class_labels_indices.csv"
    if not labels_path.is_file():
        logger.info("Downloading AudioSet class_labels_indices.csv for PANNs...")
        urllib.request.urlretrieve(
            "http://storage.googleapis.com/us_audioset/youtube_corpus/v1/csv/class_labels_indices.csv",
            labels_path,
        )

    if not os.path.isfile(checkpoint_path) or os.path.getsize(checkpoint_path) < 300_000_000:
        if os.path.isfile(checkpoint_path):
            try:
                os.remove(checkpoint_path)
            except OSError:
                pass
        logger.info("Downloading PANNs CNN14 checkpoint (~330 MB) to %s ...", checkpoint_path)
        os.makedirs(os.path.dirname(checkpoint_path), exist_ok=True)
        urllib.request.urlretrieve(
            "https://zenodo.org/record/3987831/files/Cnn14_mAP%3D0.431.pth?download=1",
            checkpoint_path,
        )
        logger.info("PANNs checkpoint ready.")


def _resolve_panns_torch_device() -> str:
    """Use CUDA only when it is actually usable for load + inference.

    On some Windows setups `torch.cuda.is_available()` can be True while
    `device_count()` is 0 or load still targets a missing GPU — then
    `torch.load(..., map_location=cuda)` raises. Default to CPU in those cases.
    """
    if os.environ.get("PANNS_FORCE_CPU", "").strip().lower() in ("1", "true", "yes"):
        return "cpu"
    try:
        import torch

        # Prefer count first: some installs report is_available True incorrectly.
        if torch.cuda.device_count() < 1:
            return "cpu"
        if not torch.cuda.is_available():
            return "cpu"
        return "cuda"
    except Exception:
        return "cpu"


def _get_audio_tagging():
    global _at_model
    if _at_model is not None:
        return _at_model

    ckpt = os.environ.get("PANN_CHECKPOINT_PATH", _default_checkpoint_path())
    _ensure_panns_assets(ckpt)

    import torch
    from panns_inference import AudioTagging

    device = _resolve_panns_torch_device()
    logger.info("Loading PANNs AudioTagging (device=%s)...", device)
    try:
        _at_model = AudioTagging(checkpoint_path=ckpt, device=device)
    except RuntimeError as e:
        err = str(e).lower()
        if device == "cuda" and ("cuda" in err or "device" in err):
            logger.warning("PANNs failed on CUDA (%s); loading on CPU.", e)
            device = "cpu"
            _at_model = AudioTagging(checkpoint_path=ckpt, device=device)
        else:
            raise
    return _at_model


def _display_name_to_event_key(name: str) -> str:
    n = name.strip().lower().replace(" ", "_").replace(",", "")
    if n == "throat_clearing":
        return "throat_clearing"
    return n


def _severity_band_to_level(band: str) -> tuple[int, str]:
    if band == "severe":
        return 5, "Severe"
    if band == "moderate":
        return 4, "Moderate"
    if band == "mild":
        return 2, "Mild"
    return 0, "None"


def _boost_severity_for_frequency(
    level: int,
    label: str,
    session_event_count: int,
    session_duration_s: float,
) -> tuple[int, str]:
    cpm = (session_event_count / max(session_duration_s, 1.0)) * 60.0
    if cpm <= 15 or level >= 5:
        return level, label
    new_level = min(5, level + 1)
    if new_level == 5:
        return 5, "Severe"
    if new_level == 4:
        return 4, "Moderate-Severe"
    if new_level == 3:
        return 3, "Moderate"
    return new_level, label


def classify_respiratory_pann(
    waveform: np.ndarray,
    sample_rate: int,
    session_event_count: int = 0,
    session_duration_s: float = 1.0,
) -> tuple[str | None, float, int, str | None]:
    """
    Run PANNs CNN14 clipwise tagging on mono float audio.

    Parameters
    ----------
    waveform : mono float32, ideally already at PANN_SAMPLE_RATE (32 kHz).
    sample_rate : source rate (will resample to 32 kHz if different).

    Returns
    -------
    (event_key, confidence_0_1, severity_level, severity_label)
    """
    x = np.asarray(waveform, dtype=np.float32).reshape(-1)
    if sample_rate != PANN_SAMPLE_RATE:
        from scipy.signal import resample as scipy_resample

        num_samples = int(len(x) * PANN_SAMPLE_RATE / sample_rate)
        x = scipy_resample(x, num_samples).astype(np.float32)

    if len(x) < PANN_CHUNK_SAMPLES:
        x = np.pad(x, (0, PANN_CHUNK_SAMPLES - len(x)))
    elif len(x) > PANN_CHUNK_SAMPLES:
        x = x[:PANN_CHUNK_SAMPLES]

    audio_batch = x[None, :]

    with _lock:
        at = _get_audio_tagging()
        clipwise, _emb = at.inference(audio_batch)
        clipwise = clipwise[0]

        resp = clipwise[list(RESPIRATORY_INDICES)]
        resp_max = float(np.max(resp))
        resp_mean = float(np.mean(resp))
        combined = max(0.65 * resp_max + 0.35 * resp_mean, resp_max * 0.85)

        speech_peak = float(np.max(clipwise[list(SPEECH_INDICES)]))
        # Softer penalty: loud speech still dampens false positives, but quiet cough/sneeze
        # is no longer wiped out by moderate speech/music peaks.
        if speech_peak > 0.38 and speech_peak > combined * 1.28:
            combined *= max(0.35, 1.0 - 0.5 * min(1.0, speech_peak / (combined + 0.08)))
        elif speech_peak > 0.22 and speech_peak > combined * 1.18:
            combined *= max(0.45, 1.0 - 0.35 * min(1.0, speech_peak / (combined + 0.08)))

        max_r = float(np.max(resp))
        wheeze_s = float(resp[0])
        cough_s = float(resp[1])
        throat_s = float(resp[2])
        sneeze_s = float(resp[3])

        # Far mic: peak respiratory score is low but sneeze is close to that peak — boost
        # effective energy so the clip still passes PANN_SCORE_THRESHOLD (cough path unchanged).
        if sneeze_s >= PANN_SNEEZE_QUIET_MIN and sneeze_s >= max_r - PANN_SNEEZE_QUIET_GAP:
            combined = max(
                combined,
                min(0.22, sneeze_s * PANN_SNEEZE_QUIET_COMBINED_MULT),
            )
        elif sneeze_s >= PANN_SNEEZE_ULTRA_MIN and sneeze_s >= max_r - PANN_SNEEZE_ULTRA_GAP:
            combined = max(
                combined,
                min(0.20, sneeze_s * PANN_SNEEZE_ULTRA_MULT),
            )

        ri = int(np.argmax(resp))

        if sneeze_s >= PANN_SNEEZE_PROMOTE_MIN:
            # Near global winner among all four respiratory classes
            if sneeze_s >= max_r - PANN_SNEEZE_NEAR_WINNER:
                ri = 3
            # Cough wins by a hair on soft/far sneezes
            elif (
                ri == 1
                and sneeze_s >= PANN_SNEEZE_RUNNER_MIN
                and (cough_s - sneeze_s) <= PANN_SNEEZE_RUNNER_MARGIN
            ):
                ri = 3
            # Cough wins argmax but sneeze is competitive — common CNN14 confusion
            elif ri == 1 and (sneeze_s + PANN_SNEEZE_COUGH_TIE_BIAS) >= cough_s:
                ri = 3
            # Wheeze wins on sharp bursts; sneeze often scores just below wheeze
            elif ri == 0 and (sneeze_s + PANN_SNEEZE_WHEEZE_TIE_BIAS) >= wheeze_s:
                ri = 3
            elif ri == 2 and (sneeze_s + PANN_SNEEZE_THROAT_TIE_BIAS) >= throat_s:
                ri = 3

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "PANNs resp sigmoid wheeze=%.3f cough=%.3f throat=%.3f sneeze=%.3f "
                "combined=%.3f ri=%d",
                wheeze_s, cough_s, float(resp[2]), sneeze_s, combined, ri,
            )

        labels = at.labels
        detected_name = labels[list(RESPIRATORY_INDICES)[ri]]

    if combined <= PANN_SCORE_THRESHOLD:
        return None, float(combined), 0, None

    event_key = _display_name_to_event_key(detected_name)
    confidence = min(1.0, float(combined) * 1.8)

    if combined > PANN_SEVERE_SCORE:
        band = "severe"
    elif combined > PANN_MODERATE_SCORE:
        band = "moderate"
    else:
        band = "mild"

    level, label = _severity_band_to_level(band)
    level, label = _boost_severity_for_frequency(
        level, label, session_event_count, session_duration_s,
    )
    return event_key, confidence, level, label


def warmup_panns() -> None:
    """Load checkpoint + run one forward pass before WebRTC audio starts.

    Without this, the first ~10–60+ seconds of model load happen while the audio
    worker drains the queue slowly, so recv() fills PANN_QUEUE_MAXSIZE and drops
    windows (see logs: "PANNs queue full").
    """
    silence = np.zeros(PANN_CHUNK_SAMPLES, dtype=np.float32)
    classify_respiratory_pann(silence, PANN_SAMPLE_RATE, 0, 1.0)
    logger.info("PANNs warmup finished (model ready for live audio).")
