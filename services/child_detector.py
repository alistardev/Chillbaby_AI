"""
services/child_detector.py

YOLOv8-based child (person) detector.

Wraps ultralytics YOLO and exposes a single `detect(frame)` method that
returns (child_present: bool, confidence: float).

Model `yolov8n.pt` (~6 MB) is auto-downloaded by ultralytics on first run.
COCO class 0 = 'person'.
"""

import logging
from ultralytics import YOLO

from config import (
    YOLO_MODEL_PATH,
    YOLO_CONFIDENCE_THRESH,
    YOLO_PERSON_CLASS_ID,
)

logger = logging.getLogger(__name__)

# ── Singleton loader ──────────────────────────────────────────────────────────
_model: YOLO | None = None


def get_model() -> YOLO:
    global _model
    if _model is None:
        logger.info("Loading YOLOv8 model: %s", YOLO_MODEL_PATH)
        _model = YOLO(YOLO_MODEL_PATH)
        logger.info("YOLOv8 model ready.")
    return _model


# ── Detection helper ──────────────────────────────────────────────────────────
def detect(frame) -> tuple[bool, float]:
    """
    Run YOLOv8 on a single BGR frame.

    Returns
    -------
    (child_present, confidence)
        child_present : True if at least one person box exceeds the threshold
        confidence    : highest person-class confidence found (0.0 if none)
    """
    model   = get_model()
    results = model(frame, verbose=False, device='cpu')[0]   # force CPU inference

    best_conf = 0.0
    for box in results.boxes:
        cls_id = int(box.cls[0])
        conf   = float(box.conf[0])
        if cls_id == YOLO_PERSON_CLASS_ID and conf >= YOLO_CONFIDENCE_THRESH:
            if conf > best_conf:
                best_conf = conf

    present = best_conf >= YOLO_CONFIDENCE_THRESH
    logger.debug("ChildDetector: present=%s conf=%.2f", present, best_conf)
    return present, best_conf
