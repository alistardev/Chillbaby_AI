"""
Emotion detection service.
Wraps the FER library and exposes a single module-level detector instance
so the model is loaded only once at startup.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Single shared FER instance (loaded once)
emotion_detector: Any | None = None
_fer_class: Any | None = None
_fer_load_error: Exception | None = None


def _resolve_fer_class() -> Any | None:
    global _fer_class, _fer_load_error
    if _fer_class is not None:
        return _fer_class
    if _fer_load_error is not None:
        return None

    try:
        # fer < 25
        from fer import FER as klass  # type: ignore
        _fer_class = klass
        return _fer_class
    except Exception as e1:
        try:
            # fer >= 25 moved FER under fer.fer
            from fer.fer import FER as klass  # type: ignore
            _fer_class = klass
            return _fer_class
        except Exception as e2:
            _fer_load_error = e2
            logger.exception(
                "FER import failed (legacy=%r, modern=%r). Emotion detection will be disabled.",
                e1,
                e2,
            )
            return None


def get_detector() -> Any | None:
    global emotion_detector
    if emotion_detector is None:
        fer_class = _resolve_fer_class()
        if fer_class is None:
            return None
        logger.info("Loading FER emotion detector (mtcnn=True)…")
        try:
            emotion_detector = fer_class(mtcnn=True)
            logger.info("FER detector ready.")
        except Exception:
            logger.exception("FER detector initialization failed. Emotion detection disabled.")
            emotion_detector = None
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
