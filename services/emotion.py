"""
Emotion detection service.
Wraps the FER library and exposes a single module-level detector instance
so the model is loaded only once at startup.
"""

import logging

try:
    from fer import FER
except ImportError:
    # fer >= 25 stopped exporting FER from fer.__init__
    from fer.fer import FER

logger = logging.getLogger(__name__)

# Single shared FER instance (loaded once)
emotion_detector: FER | None = None


def get_detector() -> FER:
    global emotion_detector
    if emotion_detector is None:
        logger.info("Loading FER emotion detector (mtcnn=True)…")
        emotion_detector = FER(mtcnn=True)
        logger.info("FER detector ready.")
    return emotion_detector


def get_max_emotion(emotions: dict) -> str:
    """Return the emotion label with the highest score, or ' ' if empty."""
    if emotions:
        return max(emotions, key=emotions.get)
    return " "


def augment_derived_emotions(raw: dict) -> dict:
    """Add composite 0–1 scores from FER's seven labels (same scale as FER).

    FER does not output these directly; they summarize common combinations:
      excited — happy + surprise
      worried — fear + sad
      tense   — angry + fear
    """
    def _get(key: str) -> float:
        for k, v in raw.items():
            if str(k).lower() == key:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return 0.0
        return 0.0

    h = _get("happy")
    sa = _get("sad")
    su = _get("surprise")
    an = _get("angry")
    fe = _get("fear")

    out: dict[str, float] = {}
    for k, v in raw.items():
        if str(k).lower() == "_state":
            continue
        try:
            out[str(k)] = float(v)
        except (TypeError, ValueError):
            continue
    out["excited"] = min(1.0, 0.52 * (h + su))
    out["worried"] = min(1.0, 0.52 * (fe + sa))
    out["tense"] = min(1.0, 0.52 * (an + fe))
    return out
