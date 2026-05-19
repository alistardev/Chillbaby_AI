"""
Copy trained food ``.pt`` into ``LOCAL_FOOD_MODEL_PATH`` when missing.

Training output often lives under ``prepare_food_dataset/`` (optional sibling folder).
Weights stay out of git (size); this avoids a manual copy when that folder is present.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from config import LOCAL_FOOD_MODEL_PATH

logger = logging.getLogger(__name__)


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def sync_food_model_if_missing() -> bool:
    """
    If ``LOCAL_FOOD_MODEL_PATH`` does not exist, copy from the first existing candidate.

    Returns True if a file now exists at the destination (was already there or copied).
    """
    dest = Path(LOCAL_FOOD_MODEL_PATH)
    if not dest.is_absolute():
        dest = _repo_root() / dest

    if dest.is_file():
        return True

    root = _repo_root()
    candidates = [
        root / "prepare_food_dataset" / "deploy_model" / "food_detector.pt",
        root / "prepare_food_dataset" / "runs" / "detect" / "runs" / "food_yolo11x_full" / "weights" / "best.pt",
        root / "prepare_food_dataset" / "runs" / "detect" / "runs" / "food_yolo11x_full" / "weights" / "last.pt",
    ]

    for src in candidates:
        if not src.is_file():
            continue
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            logger.info("Food model auto-copied: %s -> %s", src, dest)
            return True
        except Exception:
            logger.exception("Failed copying food model from %s", src)
            return False

    logger.warning(
        "No food weights at %s and no candidate under prepare_food_dataset/. "
        "Train/export or copy a .pt file manually.",
        dest,
    )
    return False
