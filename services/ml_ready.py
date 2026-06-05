"""
Server-wide ML warmup status (FER, YOLO, PANNs) — shared across all tester sessions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from aiohttp import web

import config

ML_READY_KEY = "cammy_ml_ready"


@dataclass
class MLReadyState:
    ml_warmup_done: bool = False
    panns_warmup_done: bool = False
    ml_skipped: bool = False
    panns_skipped: bool = False
    ml_error: str | None = None
    panns_error: str | None = None
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def get_ml_ready(app: web.Application) -> MLReadyState:
    return app[ML_READY_KEY]


def models_ready(state: MLReadyState) -> bool:
    ml_ok = state.ml_warmup_done or state.ml_skipped
    panns_ok = state.panns_warmup_done or state.panns_skipped
    return ml_ok and panns_ok


def bootstrap_seconds() -> float:
    return max(config.FOOD_SESSION_BOOT_DELAY_S, config.EMOTION_BOOTSTRAP_S)


def ready_payload(state: MLReadyState) -> dict:
    return {
        "ready": models_ready(state),
        "ml_warmup_done": state.ml_warmup_done,
        "panns_warmup_done": state.panns_warmup_done,
        "ml_skipped": state.ml_skipped,
        "panns_skipped": state.panns_skipped,
        "lazy_load": state.ml_skipped or state.panns_skipped,
        "ml_error": state.ml_error,
        "panns_error": state.panns_error,
        "bootstrap_seconds": bootstrap_seconds(),
        "emotion_interval_s": config.EMOTION_INTERVAL_S,
    }
