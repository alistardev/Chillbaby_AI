"""Run local food YOLO on a still image (webcam / virtual-cam test frames)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from services.child_detector import detect as yolo_detect  # noqa: E402
from services.local_food_detector import detect_food_local  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Test food detection on one image.")
    parser.add_argument("image", type=Path, help="Path to PNG/JPG frame")
    args = parser.parse_args()

    bgr = cv2.imread(str(args.image))
    if bgr is None:
        print(f"Could not read image: {args.image}", file=sys.stderr)
        return 1

    small = cv2.resize(bgr, (540, max(2, int(540 * bgr.shape[0] / bgr.shape[1]))))
    present, conf, roi = yolo_detect(small)
    print(f"child_present={present} confidence={conf:.2f}")

    if roi is not None:
        print(f"person_roi={roi}")

    foods, boxes = detect_food_local(bgr)
    print(f"food={foods}")
    if boxes:
        print(f"boxes={len(boxes)}")
    return 0 if foods else 2


if __name__ == "__main__":
    raise SystemExit(main())
