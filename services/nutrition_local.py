"""
Offline nutrition estimates from ``data/nutrition_lookup.json``.

Uses substring matching on the detected food slug (e.g. ``pizza-with-ham-baked`` → ``pizza``).
Not a substitute for lab analysis — for UI continuity without Azure.
"""

from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from typing import Any

from config import NUTRITION_LOOKUP_JSON

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _load_table() -> tuple[dict[str, dict[str, float]], dict[str, float]]:
    path = NUTRITION_LOOKUP_JSON
    if not os.path.isfile(path):
        logger.warning("Nutrition lookup file missing: %s", path)
        return {}, {}
    try:
        with open(path, encoding="utf-8") as f:
            raw: dict[str, Any] = json.load(f)
    except Exception:
        logger.exception("Failed to load nutrition lookup: %s", path)
        return {}, {}

    default = raw.pop("__default__", {}) or {}
    out: dict[str, dict[str, float]] = {}
    for k, v in raw.items():
        if not isinstance(v, dict):
            continue
        row = {kk: float(vv) for kk, vv in v.items() if isinstance(vv, (int, float))}
        if row:
            out[str(k).lower()] = row

    def_row = {k: float(v) for k, v in default.items() if isinstance(v, (int, float))}
    return out, def_row


def lookup_nutrition_for_food(food: str) -> dict[str, float]:
    """
    Return canonical nutrition dict for ``food`` label (class name or slug).
    """
    table, default = _load_table()
    if not default:
        return {}

    slug = (food or "").lower().replace("_", "-")
    if not slug:
        return dict(default)

    best_key = ""
    best_row: dict[str, float] | None = None
    for key, row in table.items():
        if key in slug and len(key) > len(best_key):
            best_key = key
            best_row = row

    if best_row:
        merged = dict(default)
        merged.update(best_row)
        return merged
    return dict(default)


def clear_nutrition_lookup_cache() -> None:
    """For tests / hot reload."""
    _load_table.cache_clear()
