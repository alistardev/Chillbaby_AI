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
import time

import cv2
import numpy as np
from av import VideoFrame
from aiortc import MediaStreamTrack
from datetime import datetime

import db
from config import (
    EMOTION_EVERY_N_FRAMES,
    FOOD_CAPTURE_INTERVAL_S,
    FOOD_WEBRTC_MAX_WIDTH,
    FRAME_RESIZE_WIDTH,
    STREAM_FOOD_FROM_VIDEO,
    YOLO_DETECT_EVERY_N,
)
from services.emotion import augment_derived_emotions, get_detector
from services.child_detector import detect as yolo_detect
from services.domain_writes import write_child_status_event
from services.food import send_frame_to_foodvisor
from models import EventType

logger = logging.getLogger(__name__)

# Thread pool for CPU-bound tasks
executor = concurrent.futures.ThreadPoolExecutor(max_workers=3)


def _run_background(coro, *, label: str) -> None:
    """Run non-critical additive writes without blocking realtime frame loop."""
    task = asyncio.create_task(coro)

    def _done(t: asyncio.Task) -> None:
        try:
            t.result()
        except Exception:
            logger.exception("Background task failed: %s", label)

    task.add_done_callback(_done)


def resize_frame(frame, new_width: int = FRAME_RESIZE_WIDTH):
    """Resize frame preserving aspect ratio (height kept even)."""
    old_h, old_w = frame.shape[:2]
    new_h = round(new_width * old_h / old_w)
    if new_h % 2 != 0:
        new_h -= 1
    return cv2.resize(frame, (new_width, new_h))


def _food_bgr_from_native(native_bgr: np.ndarray, max_w: int) -> np.ndarray:
    """Higher-res BGR for food YOLO while child path stays on FRAME_RESIZE_WIDTH."""
    if max_w <= 0:
        return resize_frame(native_bgr)
    h, w = native_bgr.shape[:2]
    if w <= max_w:
        return native_bgr.copy()
    nw = max_w
    nh = max(2, int(round(h * (nw / float(w)))))
    if nh % 2:
        nh -= 1
    return cv2.resize(native_bgr, (nw, nh), interpolation=cv2.INTER_AREA)


def _crop_person_for_fer(frame_bgr: np.ndarray, roi: tuple[int, int, int, int] | None) -> np.ndarray:
    """Zoom in on the YOLO person box so MTCNN / FER can resolve a face."""
    if roi is None:
        return frame_bgr
    x1, y1, x2, y2 = roi
    h, w = frame_bgr.shape[:2]
    bw, bh = x2 - x1, y2 - y1
    if bw < 12 or bh < 12:
        return frame_bgr
    pad = max(6, int(0.12 * max(bw, bh)))
    x1p = max(0, x1 - pad)
    y1p = max(0, y1 - pad)
    x2p = min(w, x2 + pad)
    y2p = min(h, y2 + pad)
    if x2p <= x1p + 8 or y2p <= y1p + 8:
        return frame_bgr
    return frame_bgr[y1p:y2p, x1p:x2p].copy()


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
        self._emotion_unavailable_logged = False
        # Latest person bbox (from YOLO) for FER crop — face is often too small on full-frame body shots.
        self._person_roi: tuple[int, int, int, int] | None = None
        self._last_fer_empty_log = 0.0
        # After at least one FER hit, send a one-shot UI clear when the face disappears (avoid stale scores).
        self._emotion_had_nonempty = False
        # Server-side food from WebRTC (same frames as child/emotion); throttled like canvas snapshots.
        self._last_stream_food_ts = 0.0
        self._stream_food_task: asyncio.Task | None = None

        logger.info("VideoTransformTrack created for user=%s", user_id)

    async def recv(self):
        self.frame_n += 1
        img   = await self.track.recv()
        native = img.to_ndarray(format="bgr24")
        frame = resize_frame(native)

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

        # ── Phase 2: YOLOv8 child detection (before FER so person ROI is fresh on emotion frames)
        if self.globalvars.get("processing"):
            self.yolo_frame_counter += 1
            if self.yolo_frame_counter >= YOLO_DETECT_EVERY_N:
                self.yolo_frame_counter = 0
                loop = asyncio.get_event_loop()
                present, conf, roi = await loop.run_in_executor(
                    executor, yolo_detect, frame_copy
                )
                if present and roi is not None:
                    self._person_roi = roi
                else:
                    self._person_roi = None

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
                    _run_background(
                        write_child_status_event(
                            globalvars=self.globalvars,
                            event_type=EventType.CHILD_PRESENT if present else EventType.CHILD_ABSENT,
                            confidence=round(conf, 2),
                            metadata={"source": "yolo", "status": status_msg},
                        ),
                        label="child_status_events.child_presence",
                    )

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

        # Optional WebRTC food (off by default — use browser canvas to avoid duplicate YOLO load).
        if STREAM_FOOD_FROM_VIDEO and self.globalvars.get("processing"):
            now_food = time.monotonic()
            if now_food - self._last_stream_food_ts >= FOOD_CAPTURE_INTERVAL_S:
                tfood = self._stream_food_task
                if tfood is None or tfood.done():
                    self._last_stream_food_ts = now_food
                    food_bgr = _food_bgr_from_native(native, FOOD_WEBRTC_MAX_WIDTH)
                    uid, conns, gvars, sid = (
                        self.user_id,
                        self.connections,
                        self.globalvars,
                        self.session_id,
                    )

                    async def _stream_food_job() -> None:
                        try:
                            await send_frame_to_foodvisor(food_bgr, uid, conns, gvars, sid)
                        except Exception:
                            logger.exception("Stream-side food detection failed")

                    self._stream_food_task = asyncio.create_task(_stream_food_job())

        # Run emotion detection if session is active (Phase 4: runs in thread executor)
        if self.globalvars.get("processing") and self.frame_n % EMOTION_EVERY_N_FRAMES == 0:
            self.frame_n = 0
            detector = get_detector()
            if detector is None:
                if not self._emotion_unavailable_logged:
                    logger.warning("Emotion detector unavailable; skipping FER inference.")
                    self._emotion_unavailable_logged = True
            else:
                loop = asyncio.get_event_loop()
                fer_frame = _crop_person_for_fer(frame, self._person_roi)
                self.analysis = await loop.run_in_executor(
                    executor, detector.detect_emotions, fer_frame
                )

                if self.analysis:
                    base = dict(self.analysis[0]["emotions"])
                    emotions = augment_derived_emotions(base)
                    dominant = max(emotions, key=emotions.get)
                    emotions["_state"] = 1
                    conf_d = float(emotions.get(dominant, base.get(dominant, 0.0)))
                    logger.info("Emotion detected: %s user=%s", dominant, self.user_id)
                    for ws in self.connections.values():
                        await ws.send_json(emotions)
                    self._emotion_had_nonempty = True

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
                        _run_background(
                            write_child_status_event(
                                globalvars=self.globalvars,
                                event_type=EventType.EMOTION,
                                confidence=conf_d,
                                metadata={
                                    "dominant_emotion": dominant,
                                    "emotion_scores": emotions,
                                    "fer_scores": base,
                                },
                            ),
                            label="child_status_events.emotion",
                        )
                    except Exception:
                        logger.exception("Failed to log emotion_event")
                else:
                    if self._emotion_had_nonempty:
                        self._emotion_had_nonempty = False
                        clear_emo = {"_state": 1, "_cleared": True}
                        for ws in self.connections.values():
                            await ws.send_json(clear_emo)
                    now_mono = time.monotonic()
                    if now_mono - self._last_fer_empty_log >= 20.0:
                        self._last_fer_empty_log = now_mono
                        logger.info(
                            "FER: no face (try moving closer); person_roi=%s user=%s",
                            self._person_roi is not None,
                            self.user_id,
                        )

        new_frame = VideoFrame.from_ndarray(frame_copy, format="bgr24")
        new_frame.pts       = img.pts
        new_frame.time_base = img.time_base
        return new_frame
