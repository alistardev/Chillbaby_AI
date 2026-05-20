"""
Detect invalid ``.pt`` stubs (Git LFS pointers, partial uploads) and load YOLO weights.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)

# Ultralytics can re-download these by filename when a local path is a stub.
_STOCK_ULTRALYTICS_WEIGHTS = frozenset({
    "yolov8n.pt",
    "yolov8s.pt",
    "yolov8m.pt",
    "yolov8l.pt",
    "yolov8x.pt",
    "yolo11n.pt",
    "yolo11s.pt",
    "yolo11m.pt",
    "yolo11l.pt",
    "yolo11x.pt",
})


def _read_head(path: str, n: int = 256) -> bytes:
    with open(path, "rb") as f:
        return f.read(n)


def weight_file_problem(path: str, *, min_bytes: int) -> str | None:
    """Return a human-readable problem string, or None if the file looks like real weights."""
    if not path or not os.path.isfile(path):
        return "missing"
    try:
        size = os.path.getsize(path)
    except OSError as e:
        return str(e)

    try:
        head = _read_head(path)
    except OSError as e:
        return str(e)

    if b"git-lfs.github.com" in head or (
        head.startswith(b"version ") and b"oid sha256:" in head
    ):
        return (
            f"git-lfs pointer stub ({size} bytes), not real weights — "
            "use scp/rsync of the real .pt file, not git pull"
        )

    if size < min_bytes:
        preview = head[:120].decode("utf-8", errors="replace").replace("\n", " ")
        if preview.strip() and all(ord(c) < 128 for c in preview[:40]):
            return f"text stub ({size} bytes), not a checkpoint: {preview[:80]!r}"
        return f"too small ({size} bytes); expect at least {min_bytes // (1024 * 1024)}+ MB"

    return None


def quarantine_bad_weight(path: str) -> None:
    if not path or not os.path.isfile(path):
        return
    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    dest = f"{path}.bad.{ts}"
    try:
        os.replace(path, dest)
        logger.warning("Moved invalid weight aside: %s -> %s", path, dest)
    except OSError:
        logger.exception("Could not quarantine invalid weight: %s", path)


def load_yolo(
    path: str,
    *,
    min_bytes: int = 1_000_000,
    auto_download_stock: bool = True,
):
    """
    Load Ultralytics YOLO, downloading stock weights when a local path is an LFS stub.
    """
    from ultralytics import YOLO

    problem = weight_file_problem(path, min_bytes=min_bytes)
    if problem:
        base = os.path.basename(path)
        if auto_download_stock and base in _STOCK_ULTRALYTICS_WEIGHTS:
            logger.warning(
                "Invalid %s (%s). Will download fresh %s from Ultralytics.",
                path,
                problem,
                base,
            )
            quarantine_bad_weight(path)
            model = YOLO(base)
            logger.info("Ultralytics stock model ready: %s", base)
            return model
        raise FileNotFoundError(f"{path}: {problem}")

    try:
        return YOLO(path)
    except Exception:
        base = os.path.basename(path)
        if auto_download_stock and base in _STOCK_ULTRALYTICS_WEIGHTS:
            logger.warning("torch.load failed for %s; downloading %s", path, base)
            quarantine_bad_weight(path)
            return YOLO(base)
        raise
