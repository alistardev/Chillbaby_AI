"""
Local food detection — one full-frame YOLO pass (child + food anywhere in view).

Primary: trained ``food_detector.pt``. Optional COCO ``yolov8m.pt`` pass when the
primary finds nothing (good for demo / in-hand apple until the custom model is retrained).
"""

from __future__ import annotations

import concurrent.futures
import logging
import os
import threading
import time
from datetime import datetime
from typing import Dict, List, Tuple

import cv2
import numpy as np
from ultralytics import YOLO

from services.weight_files import load_yolo, quarantine_bad_weight, weight_file_problem
from config import (
    LOCAL_FOOD_CLS_CONFIDENCE,
    LOCAL_FOOD_COCO_ALWAYS_MERGE,
    LOCAL_FOOD_COCO_CONFIDENCE,
    LOCAL_FOOD_COCO_FALLBACK_PATH,
    LOCAL_FOOD_COCO_MERGE_ON_MISS,
    LOCAL_FOOD_COCO_PREDICT_CONF,
    LOCAL_FOOD_CONFIDENCE,
    LOCAL_FOOD_DEVICE,
    LOCAL_FOOD_IOU,
    LOCAL_FOOD_MODEL_FALLBACK_PATH,
    LOCAL_FOOD_MODEL_PATH,
    LOCAL_FOOD_PREDICT_IMGSZ,
    LOCAL_FOOD_TOPK,
    LOCAL_FOOD_TRUST_CUSTOM,
    LOCAL_FOOD_UPSCALE_MAX_DIM,
    LOCAL_FOOD_WEAK_MIN,
)

logger = logging.getLogger(__name__)

# COCO food classes (yolov8m.pt) — same set as Chill-baby reference app.
# Downrank COCO labels that dominate false positives on hand-held / partial food.
_COCO_GENERIC_FACTOR: dict[str, float] = {
    "sandwich": 0.48,
    "hot dog": 0.55,
    "cake": 0.58,
    "donut": 0.62,
}

_COCO_FOOD_CLASS_IDS: dict[int, str] = {
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

_model: YOLO | None = None
_coco_model: YOLO | None = None
_model_unavailable: bool = False
_model_failed_path: str = ""
_model_failed_mtime: float = 0.0
_custom_model_missing_logged: bool = False
# Trained food_detector.pt is ~300+ MB; tiny files are usually a bad/incomplete upload.
_MIN_FOOD_PT_BYTES = 10_000_000
_last_logged_mode: str | None = None
_last_boxes_below_threshold_log: float = 0.0
_infer_lock = threading.Lock()
# Single worker — avoids stacking concurrent YOLO on CPU (main perf fix vs default executor).
_food_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="food-yolo")
_food_device: str | int | None = None


def get_food_executor() -> concurrent.futures.ThreadPoolExecutor:
    return _food_executor


def _resolve_food_device() -> str | int:
    global _food_device
    if _food_device is not None:
        return _food_device
    if LOCAL_FOOD_DEVICE:
        _food_device = int(LOCAL_FOOD_DEVICE) if LOCAL_FOOD_DEVICE.isdigit() else LOCAL_FOOD_DEVICE
        return _food_device
    try:
        import torch

        _food_device = 0 if torch.cuda.is_available() else "cpu"
    except Exception:
        _food_device = "cpu"
    logger.info("Local food YOLO device: %s", _food_device)
    return _food_device


def get_local_food_model_selection() -> str:
    preferred = LOCAL_FOOD_MODEL_PATH
    fallback = LOCAL_FOOD_MODEL_FALLBACK_PATH or ""
    if fallback and preferred != fallback and not os.path.exists(preferred):
        return fallback
    return preferred


def reset_food_model_cache() -> None:
    """Clear in-memory YOLO handles (call on server start or after replacing ``.pt``)."""
    global _model, _coco_model, _model_unavailable, _model_failed_path, _model_failed_mtime
    global _custom_model_missing_logged, _last_logged_mode
    _model = None
    _coco_model = None
    _model_unavailable = False
    _model_failed_path = ""
    _model_failed_mtime = 0.0
    _custom_model_missing_logged = False
    _last_logged_mode = None


def describe_food_model_file(path: str) -> str:
    """Human-readable size/mtime for startup logs."""
    if not path or not os.path.isfile(path):
        return "missing"
    try:
        st = os.stat(path)
        return f"{st.st_size / (1024 * 1024):.1f} MB, mtime={int(st.st_mtime)}"
    except OSError as e:
        return f"stat failed: {e}"


def validate_food_model_file(path: str) -> tuple[bool, str]:
    if not path or not os.path.isfile(path):
        return False, f"not found: {path}"
    problem = weight_file_problem(path, min_bytes=_MIN_FOOD_PT_BYTES)
    if problem:
        return False, problem
    size = os.path.getsize(path)
    return True, f"ok ({size / (1024 * 1024):.1f} MB)"


def _quarantine_corrupt_model(path: str) -> None:
    if not path or not os.path.isfile(path):
        return
    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    new_path = f"{path}.corrupt.{ts}"
    try:
        os.replace(path, new_path)
        logger.warning("Quarantined corrupt model file: %s -> %s", path, new_path)
    except Exception:
        logger.exception("Failed to quarantine corrupt model file: %s", path)


def _load_yolo(path: str, *, min_bytes: int = 1_000_000) -> YOLO:
    return load_yolo(path, min_bytes=min_bytes, auto_download_stock=True)


def _get_model() -> YOLO:
    global _model, _model_unavailable, _model_failed_path, _model_failed_mtime
    chosen = get_local_food_model_selection()
    if not chosen or not os.path.isfile(chosen):
        raise FileNotFoundError(
            f"Local food model not found at '{chosen}'. "
            "Place your checkpoint at LOCAL_FOOD_MODEL_PATH (see models/food/README.md)."
        )

    ok, reason = validate_food_model_file(chosen)
    if not ok:
        raise FileNotFoundError(f"Invalid food model at '{chosen}': {reason}")

    try:
        mtime = os.path.getmtime(chosen)
    except OSError:
        mtime = 0.0

    # New upload or replaced file after a failed load — retry instead of staying stuck.
    if _model_unavailable and (
        chosen != _model_failed_path or mtime != _model_failed_mtime
    ):
        logger.info(
            "Food model file changed since last load failure — retrying: %s (%s)",
            chosen,
            describe_food_model_file(chosen),
        )
        _model_unavailable = False
        _model = None

    if _model is None:
        if _model_unavailable:
            raise RuntimeError(
                "Local food model is unavailable after previous load failure. "
                "Fix or replace the .pt file and restart the server, or upload a new file "
                "(mtime change clears the lock without restart)."
            )
        logger.info(
            "Loading local food model: %s (%s)",
            chosen,
            describe_food_model_file(chosen),
        )
        try:
            _model = _load_yolo(chosen)
        except Exception:
            _model_unavailable = True
            _model_failed_path = chosen
            _model_failed_mtime = mtime
            logger.exception(
                "Failed to load food model at %s — using COCO/Clarifai until fixed",
                chosen,
            )
            raise
        logger.info("Local food model ready.")
    return _model


def _get_coco_model() -> YOLO | None:
    global _coco_model
    path = LOCAL_FOOD_COCO_FALLBACK_PATH
    if not path:
        return None
    if _coco_model is None:
        if not os.path.isfile(path):
            logger.info(
                "COCO food model not found at %s — downloading/using Ultralytics cache",
                path,
            )
        else:
            logger.info("Loading COCO food fallback: %s", path)
        try:
            _coco_model = _load_yolo(path, min_bytes=5_000_000)
        except Exception:
            logger.exception("Failed to load COCO food model: %s", path)
            return None
    return _coco_model


def _is_coco_checkpoint(model: YOLO, path: str) -> bool:
    """True only for stock Ultralytics COCO weights — not custom food_detector.pt (also has 'apple' classes)."""
    base = os.path.basename(path or "").lower()
    if base in ("yolov8m.pt", "yolov8n.pt", "yolov8s.pt", "yolov8l.pt", "yolov8x.pt"):
        return True
    names = getattr(model, "names", None) or {}
    # COCO detect has exactly 80 classes; custom food model has hundreds.
    try:
        return len(names) <= 80 and 47 in names
    except TypeError:
        return False


def _prepare_full_frame(bgr: np.ndarray) -> np.ndarray:
    """Full camera frame; optional upscale when the image is small (no region crops)."""
    if _resolve_food_device() == "cpu":
        return bgr
    h, w = bgr.shape[:2]
    m = max(h, w)
    if m >= LOCAL_FOOD_UPSCALE_MAX_DIM or m < 8:
        return bgr
    scale = LOCAL_FOOD_UPSCALE_MAX_DIM / m
    nw = max(1, int(round(w * scale)))
    nh = max(1, int(round(h * scale)))
    return cv2.resize(bgr, (nw, nh), interpolation=cv2.INTER_LINEAR)


def _normalize_class_name(raw: str) -> str:
    return (raw or "").strip().lower().replace("_", "-")


def friendly_food_label(raw: str) -> str:
    """
    Map training slugs (e.g. ``apple-raw-without-skin``) to a short name so COCO,
    custom YOLO, and Clarifai labels merge like cammy's simple names (``apple``).
    """
    label = _normalize_class_name(raw)
    if not label:
        return ""
    if label in _COCO_FOOD_CLASS_IDS.values():
        return label
    if label in ("hot dog", "french fries"):
        return label
    if "-" in label:
        base = label.split("-", 1)[0]
        if len(base) >= 3:
            return base
    return label


def _merge_scores(a: Dict[str, float], b: Dict[str, float]) -> Dict[str, float]:
    out = dict(a)
    for k, v in b.items():
        try:
            vf = float(v)
        except Exception:
            continue
        out[k] = max(out.get(k, 0.0), vf)
    return out


def _penalize_coco_generics(scores: Dict[str, float]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for name, conf in scores.items():
        try:
            c = float(conf)
        except Exception:
            continue
        key = friendly_food_label(name) or name
        if key:
            out[key] = round(c * _COCO_GENERIC_FACTOR.get(key, 1.0), 2)
    return out


def _log_food_mode(mode: str) -> None:
    global _last_logged_mode
    if _last_logged_mode != mode:
        _last_logged_mode = mode
        logger.info("Local food inference mode: %s", mode)


def _from_classification(r) -> Dict[str, float]:
    probs = getattr(r, "probs", None)
    if probs is None:
        return {}
    names = r.names or {}
    topk_idx = list(getattr(probs, "top5", [])[:LOCAL_FOOD_TOPK])
    topk_conf = list(getattr(probs, "top5conf", [])[:LOCAL_FOOD_TOPK])
    food_scores: Dict[str, float] = {}
    for idx, conf in zip(topk_idx, topk_conf):
        try:
            conf_f = float(conf)
        except Exception:
            continue
        if conf_f < LOCAL_FOOD_CLS_CONFIDENCE:
            continue
        label = _normalize_class_name(str(names.get(int(idx), "")))
        if label:
            food_scores[label] = max(food_scores.get(label, 0.0), round(conf_f, 2))
    return food_scores


def _from_detection(
    r,
    *,
    min_conf: float,
    coco_food_only: bool,
) -> Tuple[Dict[str, float], List[dict]]:
    global _last_boxes_below_threshold_log
    boxes = getattr(r, "boxes", None)
    if boxes is None or len(boxes) == 0:
        return {}, []

    names = r.names or {}
    h, w = 0, 0
    if hasattr(r, "orig_shape") and r.orig_shape:
        h, w = int(r.orig_shape[0]), int(r.orig_shape[1])
    food_scores: Dict[str, float] = {}
    out_boxes: List[dict] = []
    best_any = 0.0
    best_any_label = ""
    n_parsed = 0

    for box in boxes:
        try:
            cls_id = int(box.cls[0])
            conf = float(box.conf[0])
        except Exception:
            continue
        n_parsed += 1
        if coco_food_only:
            if cls_id not in _COCO_FOOD_CLASS_IDS:
                continue
            raw_name = _COCO_FOOD_CLASS_IDS[cls_id]
        else:
            raw_name = str(names.get(cls_id, str(cls_id)))

        label = friendly_food_label(raw_name)
        if conf > best_any:
            best_any = conf
            best_any_label = label or raw_name

        if w > 0 and h > 0:
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            out_boxes.append({
                "label": label or friendly_food_label(str(raw_name)),
                "conf": round(conf, 2),
                "x1": round(x1 / w, 4),
                "y1": round(y1 / h, 4),
                "x2": round(x2 / w, 4),
                "y2": round(y2 / h, 4),
            })

        if conf < min_conf or not label:
            continue
        food_scores[label] = max(food_scores.get(label, 0.0), round(conf, 2))

    if not food_scores and n_parsed > 0:
        now = time.monotonic()
        if now - _last_boxes_below_threshold_log >= 25.0:
            _last_boxes_below_threshold_log = now
            logger.info(
                "Local food: %d box(es) below conf gate (%.2f); best=%.3f (%s).",
                n_parsed,
                min_conf,
                best_any,
                best_any_label or "?",
            )
    return food_scores, out_boxes


def _predict_once(
    model: YOLO,
    bgr: np.ndarray,
    *,
    min_conf: float,
    coco_food_only: bool,
    predict_conf: float | None = None,
) -> Tuple[Dict[str, float], List[dict]]:
    task = str(getattr(model, "task", "") or "").lower()
    conf_arg = float(predict_conf) if predict_conf is not None else 0.01
    results = model.predict(
        source=bgr,
        conf=conf_arg,
        iou=LOCAL_FOOD_IOU,
        imgsz=LOCAL_FOOD_PREDICT_IMGSZ,
        max_det=20,
        verbose=False,
        device=_resolve_food_device(),
    )
    if not results:
        return {}, []
    r = results[0]
    probs = getattr(r, "probs", None)
    boxes = getattr(r, "boxes", None)
    n_boxes = len(boxes) if boxes is not None else 0
    if task == "classify" and probs is not None and (boxes is None or n_boxes == 0):
        _log_food_mode("classification")
        return _from_classification(r), []
    scores, box_list = _from_detection(r, min_conf=min_conf, coco_food_only=coco_food_only)
    _log_food_mode("detection")
    return scores, box_list


def _detect_coco_only(tile: np.ndarray) -> Tuple[Dict[str, float], List[dict]]:
    """When ``food_detector.pt`` is absent (common on fresh Ubuntu deploys)."""
    coco = _get_coco_model()
    if coco is None:
        return {}, []
    coco_scores, coco_boxes = _predict_once(
        coco,
        tile,
        min_conf=LOCAL_FOOD_COCO_CONFIDENCE,
        coco_food_only=True,
        predict_conf=LOCAL_FOOD_COCO_PREDICT_CONF,
    )
    merged = _penalize_coco_generics(coco_scores)
    if merged:
        top = max(merged, key=merged.get)
        logger.info(
            "[FOOD] Local (COCO fallback): %s (%.2f) | %s",
            top,
            merged[top],
            {k: v for k, v in sorted(merged.items(), key=lambda x: -x[1])[:5]},
        )
    return merged, coco_boxes


def _detect_sync(frame: np.ndarray) -> Tuple[Dict[str, float], List[dict]]:
    """Single full-frame inference (+ optional COCO fallback). Runs under _infer_lock."""
    with _infer_lock:
        try:
            tile = _prepare_full_frame(frame)
            chosen = get_local_food_model_selection()
            if not chosen or not os.path.isfile(chosen):
                global _custom_model_missing_logged
                if not _custom_model_missing_logged:
                    _custom_model_missing_logged = True
                    logger.warning(
                        "Custom food model missing at %s — using COCO yolov8m only until you copy "
                        "food_detector.pt (see models/food/README.md). Clarifai-only mode is weaker.",
                        chosen,
                    )
                return _detect_coco_only(tile)
            model = _get_model()
            use_coco_filter = _is_coco_checkpoint(model, chosen)
            gate = LOCAL_FOOD_COCO_CONFIDENCE if use_coco_filter else LOCAL_FOOD_CONFIDENCE
            custom_scores, boxes = _predict_once(
                model, tile, min_conf=gate, coco_food_only=use_coco_filter
            )
            merged = dict(custom_scores)
            custom_best = max(custom_scores.values()) if custom_scores else 0.0

            # Second YOLO pass when custom is weak — catches COCO foods custom missed.
            run_coco = not use_coco_filter and custom_best < LOCAL_FOOD_TRUST_CUSTOM and (
                LOCAL_FOOD_COCO_ALWAYS_MERGE
                or (LOCAL_FOOD_COCO_MERGE_ON_MISS and not merged)
            )

            if run_coco:
                coco = _get_coco_model()
                if coco is not None:
                    coco_scores, coco_boxes = _predict_once(
                        coco,
                        tile,
                        min_conf=LOCAL_FOOD_COCO_CONFIDENCE,
                        coco_food_only=True,
                        predict_conf=LOCAL_FOOD_COCO_PREDICT_CONF,
                    )
                    coco_scores = _penalize_coco_generics(coco_scores)
                    merged = _merge_scores(merged, coco_scores)
                    if coco_boxes:
                        boxes = coco_boxes

            if merged:
                top = max(merged, key=merged.get)
                logger.info(
                    "[FOOD] Local: %s (%.2f) | %s",
                    top,
                    merged[top],
                    {k: v for k, v in sorted(merged.items(), key=lambda x: -x[1])[:5]},
                )
            else:
                logger.info(
                    "[FOOD] Local: no food (custom_best=%.2f, coco_ran=%s)",
                    custom_best,
                    run_coco,
                )
            return merged, boxes
        except FileNotFoundError as e:
            logger.warning("%s — using COCO yolov8m only.", e)
            return _detect_coco_only(tile)
        except RuntimeError as e:
            logger.warning("%s — using COCO yolov8m only.", e)
            return _detect_coco_only(tile)
        except Exception:
            logger.exception("Local food detection failed — using COCO yolov8m only.")
            return _detect_coco_only(tile)


def detect_food_local(frame) -> Tuple[Dict[str, float], List[dict]]:
    """
    Run local YOLO on the **entire** BGR frame (no percentage crops).

    Returns ``(food_scores, boxes)`` with boxes normalized 0–1 to the input frame.
    """
    if frame is None or not hasattr(frame, "shape") or frame.size == 0:
        return {}, []
    return _detect_sync(frame)


def warmup_food_yolo() -> None:
    """Load food weights + one inference pass so the first live frame is not delayed."""
    import numpy as np

    from config import LOCAL_FOOD_COCO_ALWAYS_MERGE, LOCAL_FOOD_COCO_MERGE_ON_MISS

    _get_model()
    if LOCAL_FOOD_COCO_ALWAYS_MERGE or LOCAL_FOOD_COCO_MERGE_ON_MISS:
        _get_coco_model()
    dummy = np.zeros((480, 640, 3), dtype=np.uint8)
    detect_food_local(dummy)
    logger.info("Food YOLO warmup done.")
