"""
Local food detector (no external API required).

Uses an Ultralytics classification model and keeps only labels that look like
food classes. This is intentionally conservative and can be improved by
swapping in a dedicated food model later.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from typing import Dict

from ultralytics import YOLO

from config import (
    LOCAL_FOOD_CONFIDENCE,
    LOCAL_FOOD_MODEL_FALLBACK_PATH,
    LOCAL_FOOD_MODEL_PATH,
    LOCAL_FOOD_TOPK,
)
from services.child_detector import get_model as get_yolo_detect_model

logger = logging.getLogger(__name__)

_model: YOLO | None = None
_model_unavailable: bool = False

# Broad food keywords for filtering generic classification labels.
_FOOD_HINTS = (
    "food",
    "dish",
    "meal",
    "fruit",
    "vegetable",
    "salad",
    "soup",
    "bread",
    "rice",
    "pasta",
    "pizza",
    "burger",
    "sandwich",
    "egg",
    "milk",
    "cheese",
    "yogurt",
    "butter",
    "meat",
    "fish",
    "chicken",
    "beef",
    "pork",
    "seafood",
    "shrimp",
    "crab",
    "lobster",
    "noodle",
    "bean",
    "nut",
    "peanut",
    "almond",
    "cashew",
    "banana",
    "apple",
    "orange",
    "grape",
    "strawberry",
    "chocolate",
    "cookie",
    "cake",
    "ice cream",
    "plate",
    "bowl",
    "dishware",
    "tableware",
    "cup",
)

_NON_FOOD_BLOCKLIST = {
    "envelope",
    "pick",
    "packet",
    "book jacket",
    "menu",
    "web site",
}

_PIZZA_HINTS = ("pizza", "pie", "flatbread", "calzone", "focaccia")
_CANONICAL_KEYWORDS: dict[str, tuple[str, ...]] = {
    "pizza": ("pizza", "pie", "flatbread", "calzone", "focaccia"),
    "sandwich": ("sandwich", "sub", "burger", "hot dog", "wrap", "taco"),
    "pasta": ("pasta", "spaghetti", "macaroni", "lasagna", "noodle", "ramen"),
    "rice": ("rice", "risotto", "biryani", "pilaf", "paella"),
    "salad": ("salad", "coleslaw", "vegetable", "veggie", "greens"),
    "soup": ("soup", "stew", "broth", "chowder", "curry"),
    "cake": ("cake", "pastry", "brownie", "cookie", "donut", "dessert"),
    "fruit": ("banana", "apple", "orange", "grape", "strawberry", "fruit", "berries"),
    "meat": ("beef", "chicken", "pork", "meat", "steak", "sausage"),
    "seafood": ("fish", "shrimp", "crab", "lobster", "seafood", "salmon", "tuna"),
    "mixed_food": (
        "plate",
        "bowl",
        "dish",
        "dishware",
        "tableware",
        "meal",
        "food",
        "platter",
        "casserole",
    ),
}
_COCO_FOOD_CLASS_IDS = {
    46: "banana",
    47: "apple",
    48: "sandwich",
    49: "orange",
    50: "broccoli",
    51: "carrot",
    52: "hot dog",
    53: "pizza",
    54: "donut",
    55: "cake",
}
_COCO_FRUIT_CLASS_IDS = {46, 47, 49}


def get_local_food_model_selection() -> str:
    """
    Resolve which local model path will be used at runtime.
    """
    preferred = LOCAL_FOOD_MODEL_PATH
    fallback = LOCAL_FOOD_MODEL_FALLBACK_PATH
    if preferred and preferred != fallback and not os.path.exists(preferred):
        return fallback
    return preferred


def _quarantine_corrupt_model(path: str) -> None:
    """
    Move a likely-corrupt model file out of the way so Ultralytics can
    re-download/recreate it on the next load attempt.
    """
    if not path or not os.path.isfile(path):
        return
    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    new_path = f"{path}.corrupt.{ts}"
    try:
        os.replace(path, new_path)
        logger.warning("Quarantined corrupt model file: %s -> %s", path, new_path)
    except Exception:
        logger.exception("Failed to quarantine corrupt model file: %s", path)


def _get_model() -> YOLO:
    global _model, _model_unavailable
    if _model is None:
        if _model_unavailable:
            raise RuntimeError("Local food model is unavailable after previous load failure.")

        preferred = LOCAL_FOOD_MODEL_PATH
        fallback = LOCAL_FOOD_MODEL_FALLBACK_PATH
        chosen = get_local_food_model_selection()

        if chosen == fallback and preferred != fallback and not os.path.exists(preferred):
            logger.warning(
                "Preferred food model not found at '%s'; falling back to '%s'.",
                preferred,
                fallback,
            )

        logger.info("Loading local food model: %s", chosen)
        try:
            _model = YOLO(chosen)
        except OSError as e:
            # Common with interrupted/incomplete .pt files on disk.
            logger.warning("Local model load failed (%s). Attempting one-time recovery.", e)
            _quarantine_corrupt_model(chosen)
            _model = YOLO(chosen)
        except Exception:
            # Mark unavailable so we don't retry and spam every frame.
            _model_unavailable = True
            raise

        logger.info("Local food model ready.")
    return _model


def _normalize_label(label: str) -> str | None:
    s = (label or "").strip().lower()
    if not s:
        return None
    s = s.replace("_", " ")
    if s in _NON_FOOD_BLOCKLIST:
        return None

    def _has_keyword(text: str, keyword: str) -> bool:
        kw = (keyword or "").strip().lower()
        if not kw:
            return False
        if " " in kw:
            return kw in text
        return re.search(rf"\b{re.escape(kw)}\b", text) is not None

    for canonical, keywords in _CANONICAL_KEYWORDS.items():
        if any(_has_keyword(s, k) for k in keywords):
            return canonical

    if any(_has_keyword(s, hint) for hint in _FOOD_HINTS):
        return s
    return None


def detect_food_local(frame) -> Dict[str, float]:
    """
    Return {food_name: confidence} from local model only.
    """
    try:
        model = _get_model()
        result = model(frame, verbose=False, device="cpu")[0]
        probs = getattr(result, "probs", None)
        if probs is None:
            return {}

        names = result.names or {}
        topk_idx = list(getattr(probs, "top5", [])[:LOCAL_FOOD_TOPK])
        topk_conf = list(getattr(probs, "top5conf", [])[:LOCAL_FOOD_TOPK])

        food_scores: Dict[str, float] = {}
        raw_scores: list[tuple[str, float]] = []
        for idx, conf in zip(topk_idx, topk_conf):
            try:
                conf_f = float(conf)
            except Exception:
                continue
            raw_label = str(names.get(int(idx), "")).lower()
            raw_scores.append((raw_label, conf_f))
            if conf_f < LOCAL_FOOD_CONFIDENCE:
                continue
            label = _normalize_label(raw_label)
            if not label:
                continue
            food_scores[label] = max(food_scores.get(label, 0.0), round(conf_f, 2))

        # Also use YOLO object detection food classes from COCO
        # (pizza/sandwich/fruit classes) and merge with cls-model scores.
        det_scores: Dict[str, float] = {}
        try:
            detect_model = get_yolo_detect_model()
            det_result = detect_model(frame, verbose=False, device="cpu")[0]
            for box in getattr(det_result, "boxes", []):
                try:
                    cls_id = int(box.cls[0])
                    conf = float(box.conf[0])
                except Exception:
                    continue
                if cls_id not in _COCO_FOOD_CLASS_IDS or conf < 0.10:
                    continue
                food_name = _COCO_FOOD_CLASS_IDS[cls_id]

                # Fruit classes are noisy at low confidence (apple/lemon often
                # collapses to banana on generic models). Keep specific fruit
                # only with stronger confidence; otherwise treat as mixed.
                if cls_id in _COCO_FRUIT_CLASS_IDS and conf < 0.35:
                    food_name = "mixed_food"

                det_scores[food_name] = max(det_scores.get(food_name, 0.0), round(conf, 2))
        except Exception:
            logger.debug("YOLO object food fallback failed.", exc_info=True)

        for name, conf in det_scores.items():
            boosted = min(1.0, conf + 0.12)
            food_scores[name] = max(food_scores.get(name, 0.0), round(boosted, 2))

        # Priority correction: when detector sees pizza, avoid pasta drift.
        det_pizza = det_scores.get("pizza", 0.0)
        if det_pizza >= 0.10:
            pizza_score = max(food_scores.get("pizza", 0.0), round(min(1.0, det_pizza + 0.22), 2))
            food_scores["pizza"] = pizza_score
            pasta_score = food_scores.get("pasta", 0.0)
            if pasta_score and pizza_score >= (pasta_score * 0.8):
                food_scores["pasta"] = round(max(0.0, pasta_score - 0.18), 2)

        # If still no food-like labels matched, emit a neutral class instead of random
        # non-food labels (e.g. "envelope"/"pick") from generic classifiers.
        if not food_scores and raw_scores:
            raw_scores.sort(key=lambda x: x[1], reverse=True)
            # Pizza-specific rescue: generic cls often predicts pie/flatbread-like
            # classes for pizza slices with low confidence.
            for raw_label, conf in raw_scores:
                label_s = (raw_label or "").strip().lower().replace("_", " ")
                if conf >= 0.08 and any(h in label_s for h in _PIZZA_HINTS):
                    food_scores["pizza"] = round(conf, 2)
                    return food_scores

            _, top_conf = raw_scores[0]
            if top_conf >= max(0.08, LOCAL_FOOD_CONFIDENCE * 0.6):
                food_scores["unknown_food"] = round(top_conf, 2)
        return food_scores
    except Exception:
        logger.exception("Local food detection failed")
        return {}
