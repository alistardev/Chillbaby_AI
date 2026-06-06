"""
VideoTransformTrack – WebRTC video processing service.

Receives frames from the browser webcam via aiortc, runs:
  - FER emotion detection on a timer (never blocks frame delivery)
  - YOLOv8 child (person) detection on a frame interval (non-blocking)

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
    EMOTION_BOOTSTRAP_S,
    EMOTION_INTERVAL_S,
    FER_MAX_DIM,
    FER_USE_MTCNN,
    FOOD_CAPTURE_INTERVAL_S,
    FOOD_WEBRTC_MAX_WIDTH,
    FRAME_RESIZE_WIDTH,
    STREAM_FOOD_FROM_VIDEO,
    YOLO_DETECT_EVERY_N,
)
from services.emotion import augment_derived_emotions, get_detector
from services.child_detector import detect as yolo_detect
from services.domain_writes import write_child_status_event
from services.food import is_food_pipeline_busy, send_frame_to_foodvisor
from models import EventType

logger = logging.getLogger(__name__)

# Dedicated workers — FER and child YOLO must not queue behind each other on one pool.
_yolo_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="yolo-child")
_fer_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="fer")


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


def _scale_roi(
    roi: tuple[int, int, int, int] | None,
    from_w: int,
    from_h: int,
    to_w: int,
    to_h: int,
) -> tuple[int, int, int, int] | None:
    """Map a pixel ROI from one frame size to another (e.g. resized → native)."""
    if roi is None or from_w < 1 or from_h < 1:
        return None
    x1, y1, x2, y2 = roi
    sx = to_w / float(from_w)
    sy = to_h / float(from_h)
    return (
        int(round(x1 * sx)),
        int(round(y1 * sy)),
        int(round(x2 * sx)),
        int(round(y2 * sy)),
    )


def _prepare_fer_frame(frame_bgr: np.ndarray, max_dim: int = FER_MAX_DIM) -> np.ndarray:
    """Whole webcam frame scaled for FER — same idea as a normal camera app."""
    h, w = frame_bgr.shape[:2]
    longest = max(h, w)
    if longest <= max_dim:
        return frame_bgr.copy()
    scale = max_dim / float(longest)
    nw = max(2, int(round(w * scale)))
    nh = max(2, int(round(h * scale)))
    if nw % 2:
        nw -= 1
    if nh % 2:
        nh -= 1
    return cv2.resize(frame_bgr, (nw, nh), interpolation=cv2.INTER_AREA)


def _center_crop(frame_bgr: np.ndarray, frac: float = 0.92) -> np.ndarray:
    """Slight center crop — ignores letterbox edges without cutting off a centered face."""
    h, w = frame_bgr.shape[:2]
    cw = max(32, int(w * frac))
    ch = max(32, int(h * frac))
    x1 = (w - cw) // 2
    y1 = (h - ch) // 2
    return frame_bgr[y1 : y1 + ch, x1 : x1 + cw].copy()


def _clamp_roi(x1: int, y1: int, x2: int, y2: int, w: int, h: int) -> tuple[int, int, int, int] | None:
    x1p = max(0, min(x1, w - 1))
    y1p = max(0, min(y1, h - 1))
    x2p = max(x1p + 8, min(x2, w))
    y2p = max(y1p + 8, min(y2, h))
    if x2p <= x1p + 8 or y2p <= y1p + 8:
        return None
    return x1p, y1p, x2p, y2p


def _head_square_from_roi(
    frame_bgr: np.ndarray,
    roi: tuple[int, int, int, int],
) -> np.ndarray | None:
    """Optional extra crop when YOLO person box exists (full-body shots)."""
    h, w = frame_bgr.shape[:2]
    x1, y1, x2, y2 = roi
    bw, bh = max(1, x2 - x1), max(1, y2 - y1)
    aspect = bh / float(bw)
    head_frac = 0.55 if aspect < 1.35 else 0.30
    head_h = max(48, int(bh * head_frac))
    side = max(bw, head_h)
    cx = x1 + bw // 2
    x1p = cx - side // 2
    y1p = y1 - int(side * 0.04)
    clamped = _clamp_roi(x1p, y1p, x1p + side, y1p + side, w, h)
    if clamped is None:
        return None
    x1, y1, x2, y2 = clamped
    return frame_bgr[y1:y2, x1:x2].copy()


def _fer_crop_candidates(
    frame_bgr: np.ndarray,
    roi: tuple[int, int, int, int] | None,
) -> list[np.ndarray]:
    """Webcam-first: full frame, then fallbacks only if needed (Haar / no mtcnn)."""
    full = _prepare_fer_frame(frame_bgr)
    candidates: list[np.ndarray] = [full]
    seen: set[tuple[int, int]] = {(full.shape[1], full.shape[0])}

    def _add(crop: np.ndarray | None) -> None:
        if crop is None or crop.size == 0:
            return
        key = (crop.shape[1], crop.shape[0])
        if key in seen:
            return
        seen.add(key)
        candidates.append(_prepare_fer_frame(crop))

    if FER_USE_MTCNN:
        # MTCNN locates faces in the full frame — extra crops rarely help and cost CPU.
        return candidates

    _add(_center_crop(frame_bgr))
    if roi is not None:
        _add(_head_square_from_roi(frame_bgr, roi))
    return candidates


class VideoTransformTrack(MediaStreamTrack):
    """
    A video stream track that transforms frames from another track.
    """
    kind = "video"

    def __init__(self, track, transform: str, user_id: str, connections: dict,
                 globalvars: dict, session_id=None, food_user_id: str | None = None):
        super().__init__()
        self.track      = track
        _ = transform  # from WebRTC offer; reserved for future video transforms
        self.user_id    = user_id
        self.food_user_id = food_user_id or user_id
        self.connections = connections
        self.globalvars  = globalvars
        self.session_id  = session_id

        self.frame_n   = 0

        # Frame geometry (populated on first frame)
        self.width = self.height = 0
        self.start_row = self.start_col = 0
        self.end_row   = self.end_col   = 0

        # Phase 2: child detection state
        self.child_present: bool | None = None  # None = not yet checked
        self.yolo_frame_counter = 0
        self._emotion_unavailable_logged = False
        self._person_roi: tuple[int, int, int, int] | None = None
        self._person_roi_ts = 0.0
        self._person_roi_ttl_s = 4.0
        self._last_fer_empty_log = 0.0
        self._emotion_had_nonempty = False
        self._last_fer_scheduled_ts = 0.0
        self._last_fer_finished_ts = 0.0
        self._fer_task: asyncio.Task | None = None
        self._fer_pending: tuple[np.ndarray, tuple[int, int, int, int] | None] | None = None
        self._fer_first_ok = False
        self._session_started_mono: float | None = None
        self._yolo_task: asyncio.Task | None = None
        self._last_stream_food_ts = 0.0
        self._stream_food_task: asyncio.Task | None = None

        logger.info("VideoTransformTrack created for user=%s", user_id)

    async def _run_fer(self, crop_candidates: list[np.ndarray]) -> None:
        """FER off the hot path — try head-focused crops until a face is found."""
        detector = get_detector()
        if detector is None or not crop_candidates:
            return
        loop = asyncio.get_running_loop()
        analysis = None
        t0 = time.monotonic()
        tried = 0
        for raw_crop in crop_candidates:
            fer_bgr = raw_crop
            tried += 1
            try:
                analysis = await loop.run_in_executor(
                    _fer_executor, detector.detect_emotions, fer_bgr
                )
            except Exception:
                logger.exception("FER inference failed")
                return
            if analysis:
                break

        elapsed_ms = int((time.monotonic() - t0) * 1000)
        if elapsed_ms > 1500:
            logger.warning("FER slow: %dms (set FER_USE_MTCNN=0 for faster CPU inference)", elapsed_ms)

        if analysis:
            base = dict(analysis[0]["emotions"])
            emotions = augment_derived_emotions(base)
            dominant = max(base, key=base.get) if base else "neutral"
            emotions["_state"] = 1
            conf_d = float(emotions.get(dominant, base.get(dominant, 0.0)))
            logger.info(
                "Emotion detected: %s user=%s (%dms, crop_try=%d/%d)",
                dominant,
                self.user_id,
                elapsed_ms,
                tried,
                len(crop_candidates),
            )
            if not self.connections:
                logger.warning("Emotion emit: no WebSocket clients user=%s", self.user_id)
            dead: list[str] = []
            for uid, ws in list(self.connections.items()):
                try:
                    await ws.send_json(emotions)
                except Exception:
                    logger.exception("Emotion emit failed for token=%s", uid[:16])
                    dead.append(uid)
            for uid in dead:
                self.connections.pop(uid, None)
            self._emotion_had_nonempty = True
            self._fer_first_ok = True
            self.globalvars["_fer_first_result"] = True

            doc = {
                "session_id":       self.session_id,
                "timestamp":        datetime.utcnow(),
                "dominant_emotion": dominant,
                "scores":           emotions,
                "fer_scores":       base,
            }
            if self.globalvars.get("testerId"):
                doc["tester_id"] = self.globalvars["testerId"]

            async def _persist_emo() -> None:
                try:
                    await db.emotion_events().insert_one(doc)
                except Exception:
                    logger.exception("Failed to log emotion_event")
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

            asyncio.create_task(_persist_emo())
        else:
            if self._emotion_had_nonempty:
                self._emotion_had_nonempty = False
                clear_emo = {"_state": 1, "_cleared": True}
                for uid, ws in list(self.connections.items()):
                    try:
                        await ws.send_json(clear_emo)
                    except Exception:
                        self.connections.pop(uid, None)
            now_mono = time.monotonic()
            if now_mono - self._last_fer_empty_log >= 20.0:
                self._last_fer_empty_log = now_mono
                logger.info(
                    "FER: no face (try moving closer); person_roi=%s user=%s",
                    self._person_roi is not None,
                    self.user_id,
                )

    async def _run_yolo(self, frame_bgr: np.ndarray) -> None:
        loop = asyncio.get_running_loop()
        try:
            present, conf, roi = await loop.run_in_executor(
                _yolo_executor, yolo_detect, frame_bgr
            )
        except Exception:
            logger.exception("Child YOLO failed")
            return

        now_mono = time.monotonic()
        if present and roi is not None:
            self._person_roi = roi
            self._person_roi_ts = now_mono
        elif now_mono - self._person_roi_ts > self._person_roi_ttl_s:
            self._person_roi = None

        self.globalvars["personPresent"] = present

        if present != self.child_present:
            self.child_present = present
            status_msg = "present" if present else "missing"
            logger.info(
                "Child detection state changed: %s (conf=%.2f) user=%s",
                status_msg, conf, self.user_id
            )
            payload = {
                "_state":        6,
                "child_present": present,
                "confidence":    round(conf, 2),
            }
            for ws in self.connections.values():
                await ws.send_json(payload)

            _run_background(
                write_child_status_event(
                    globalvars=self.globalvars,
                    event_type=EventType.CHILD_PRESENT if present else EventType.CHILD_ABSENT,
                    confidence=round(conf, 2),
                    metadata={"source": "yolo", "status": status_msg},
                ),
                label="child_status_events.child_presence",
            )

            if not present:
                try:
                    alert_doc = {
                        "session_id": self.session_id,
                        "timestamp":  datetime.utcnow(),
                        "alert_type": "child_missing",
                        "confidence": round(conf, 2),
                        "metadata":   {},
                    }
                    if self.globalvars.get("testerId"):
                        alert_doc["tester_id"] = self.globalvars["testerId"]
                    await db.alert_events().insert_one(alert_doc)
                except Exception:
                    logger.exception("Failed to log child_missing alert")

    def _schedule_fer(self, native_bgr: np.ndarray, roi_native: tuple[int, int, int, int] | None) -> None:
        self._fer_pending = (native_bgr, roi_native)
        t = self._fer_task
        if t is not None and not t.done():
            return
        self.globalvars["_fer_active"] = True
        self._fer_task = asyncio.create_task(self._fer_worker())

    async def _fer_worker(self) -> None:
        try:
            while self._fer_pending is not None:
                native_bgr, roi_native = self._fer_pending
                self._fer_pending = None
                crops = _fer_crop_candidates(native_bgr, roi_native)
                if crops:
                    await self._run_fer(crops)
        finally:
            self._fer_task = None
            self.globalvars["_fer_active"] = False
            self._last_fer_finished_ts = time.monotonic()
            if self._fer_pending is not None:
                self._fer_task = asyncio.create_task(self._fer_worker())

    def _schedule_yolo(self, frame_bgr: np.ndarray) -> None:
        t = self._yolo_task
        if t is not None and not t.done():
            return
        self._yolo_task = asyncio.create_task(self._run_yolo(frame_bgr.copy()))

    async def recv(self):
        self.frame_n += 1
        img   = await self.track.recv()
        native = img.to_ndarray(format="bgr24")
        frame = resize_frame(native)

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

        if self.globalvars.get("processing"):
            if self._session_started_mono is None:
                self._session_started_mono = time.monotonic()
            food_busy = is_food_pipeline_busy(self.food_user_id)

            # Child YOLO — defer while food inference or emotion bootstrap (CPU headroom for FER).
            now_boot = time.monotonic()
            in_emotion_bootstrap = (
                EMOTION_BOOTSTRAP_S > 0
                and not self._fer_first_ok
                and self._session_started_mono is not None
                and now_boot - self._session_started_mono < EMOTION_BOOTSTRAP_S
            )
            if not food_busy and not in_emotion_bootstrap:
                self.yolo_frame_counter += 1
                if self.yolo_frame_counter >= YOLO_DETECT_EVERY_N:
                    self.yolo_frame_counter = 0
                    self._schedule_yolo(frame_copy)

            # FER — full webcam frame; interval measured from last completed run (not schedule).
            now_emo = time.monotonic()
            fer_due = (
                self._last_fer_finished_ts == 0.0
                or now_emo - self._last_fer_finished_ts >= EMOTION_INTERVAL_S
            )
            if fer_due:
                detector = get_detector()
                if detector is None:
                    if not self._emotion_unavailable_logged:
                        logger.warning("Emotion detector unavailable; skipping FER inference.")
                        self._emotion_unavailable_logged = True
                else:
                    self._last_fer_scheduled_ts = now_emo
                    nat_h, nat_w = native.shape[:2]
                    fra_h, fra_w = frame_copy.shape[:2]
                    roi_native = _scale_roi(self._person_roi, fra_w, fra_h, nat_w, nat_h)
                    self._schedule_fer(native, roi_native)

            if STREAM_FOOD_FROM_VIDEO:
                now_food = time.monotonic()
                if now_food - self._last_stream_food_ts >= FOOD_CAPTURE_INTERVAL_S:
                    tfood = self._stream_food_task
                    if tfood is None or tfood.done():
                        self._last_stream_food_ts = now_food
                        food_bgr = _food_bgr_from_native(native, FOOD_WEBRTC_MAX_WIDTH)
                        uid, conns, gvars, sid = (
                            self.food_user_id,
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

        new_frame = VideoFrame.from_ndarray(frame_copy, format="bgr24")
        new_frame.pts       = img.pts
        new_frame.time_base = img.time_base
        return new_frame
