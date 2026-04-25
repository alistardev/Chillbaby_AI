"""
VideoTransformTrack – WebRTC video processing service.

Receives frames from the browser webcam via aiortc, runs:
  - MediaPipe FaceMesh (frame resize + crop)
  - FER emotion detection every EMOTION_EVERY_N_FRAMES frames
  - YOLOv8 child (person) detection every YOLO_DETECT_EVERY_N frames (Phase 2)

Broadcasts results over the shared WebSocket connections dict.
"""

import logging
import asyncio
import concurrent.futures

import cv2
import numpy as np
from av import VideoFrame
from aiortc import MediaStreamTrack
from datetime import datetime

import db
from config import (
    EMOTION_EVERY_N_FRAMES,
    FRAME_RESIZE_WIDTH,
    YOLO_DETECT_EVERY_N,
)
from services.emotion import augment_derived_emotions, get_detector
from services.child_detector import detect as yolo_detect

logger = logging.getLogger(__name__)

# Thread pool for CPU-bound tasks
executor = concurrent.futures.ThreadPoolExecutor(max_workers=3)


def resize_frame(frame, new_width: int = FRAME_RESIZE_WIDTH):
    """Resize frame preserving aspect ratio (height kept even)."""
    old_h, old_w = frame.shape[:2]
    new_h = round(new_width * old_h / old_w)
    if new_h % 2 != 0:
        new_h -= 1
    return cv2.resize(frame, (new_width, new_h))


class VideoTransformTrack(MediaStreamTrack):
    """
    A video stream track that transforms frames from another track.
    """
    kind = "video"

    def __init__(self, track, transform: str, user_id: str, connections: dict,
                 globalvars: dict, session_id=None):
        super().__init__()
        self.track      = track
        _ = transform  # from WebRTC offer; reserved for future video transforms
        self.user_id    = user_id
        self.connections = connections
        self.globalvars  = globalvars
        self.session_id  = session_id

        self.frame_n   = 0
        self.analysis  = []

        # Frame geometry (populated on first frame)
        self.width = self.height = 0
        self.start_row = self.start_col = 0
        self.end_row   = self.end_col   = 0

        # Phase 2: child detection state
        self.child_present: bool | None = None  # None = not yet checked
        self.yolo_frame_counter = 0

        logger.info("VideoTransformTrack created for user=%s", user_id)

    async def recv(self):
        self.frame_n += 1
        img   = await self.track.recv()
        frame = img.to_ndarray(format="bgr24")
        frame = resize_frame(frame)

        # On first frame, compute food-region overlay coordinates
        if self.width == 0:
            self.height, self.width = frame.shape[:2]
            self.start_row = int(0.75 * self.height)
            self.start_col = 0
            self.end_row   = self.start_row + int(0.25 * self.height)
            self.end_col   = self.start_col + int(0.50 * self.width)
            food_rect = "foodrect\\0\\70\\50\\30"
            ws = self.connections.get(self.user_id)
            if ws:
                await ws.send_str(food_rect)
            logger.debug("Food rect sent: %s", food_rect)

        frame_copy = frame.copy()

        # Run emotion detection if session is active (Phase 4: runs in thread executor)
        if self.globalvars.get("processing") and self.frame_n % EMOTION_EVERY_N_FRAMES == 0:
            self.frame_n = 0
            detector     = get_detector()
            loop         = asyncio.get_event_loop()

            # FER is CPU-heavy — run in thread so it doesn't block the event loop
            self.analysis = await loop.run_in_executor(
                executor, detector.detect_emotions, frame.copy()
            )

            if self.analysis:
                base = dict(self.analysis[0]['emotions'])
                emotions = augment_derived_emotions(base)
                emotions['_state'] = 1
                dominant = max(emotions, key=emotions.get)
                logger.info("Emotion detected: %s user=%s", dominant, self.user_id)
                for ws in self.connections.values():
                    await ws.send_json(emotions)

                # Persist emotion event to MongoDB
                try:
                    doc = {
                        "session_id":       self.session_id,
                        "timestamp":        datetime.utcnow(),
                        "dominant_emotion": dominant,
                        "scores":           emotions,
                        "fer_scores":       base,
                    }
                    await db.emotion_events().insert_one(doc)
                except Exception:
                    logger.exception("Failed to log emotion_event")

        # ── Phase 2: YOLOv8 child detection ─────────────────────────────────
        if self.globalvars.get("processing"):
            self.yolo_frame_counter += 1
            if self.yolo_frame_counter >= YOLO_DETECT_EVERY_N:
                self.yolo_frame_counter = 0
                loop = asyncio.get_event_loop()
                present, conf = await loop.run_in_executor(
                    executor, yolo_detect, frame_copy
                )

                # Only act on state transitions to avoid flooding
                if present != self.child_present:
                    self.child_present = present
                    status_msg = "present" if present else "missing"
                    logger.info(
                        "Child detection state changed: %s (conf=%.2f) user=%s",
                        status_msg, conf, self.user_id
                    )

                    # Broadcast to frontend (_state 6)
                    payload = {
                        "_state":        6,
                        "child_present": present,
                        "confidence":    round(conf, 2),
                    }
                    for ws in self.connections.values():
                        await ws.send_json(payload)

                    # Log transition to MongoDB alert_events
                    if not present:   # only log "missing" transitions as alerts
                        try:
                            await db.alert_events().insert_one({
                                "session_id": self.session_id,
                                "timestamp":  datetime.utcnow(),
                                "alert_type": "child_missing",
                                "confidence": round(conf, 2),
                                "metadata":   {},
                            })
                        except Exception:
                            logger.exception("Failed to log child_missing alert")

        new_frame = VideoFrame.from_ndarray(frame_copy, format="bgr24")
        new_frame.pts       = img.pts
        new_frame.time_base = img.time_base
        return new_frame
