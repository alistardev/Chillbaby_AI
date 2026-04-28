"""
services/audio_track.py – Phase 3 (PANNs)

AudioTransformTrack
--------------------
Receives raw audio frames from the WebRTC stream, buffers ~1 s of audio
at 32 kHz, then runs PANNs CNN14 (panns-inference). Uses a sliding hop
so classification repeats sooner than a full extra second (reduces missed
rapid coughs/sneezes).

Detected events:
  cough, sneeze, wheeze, throat_clearing — with speech-peak penalty.

On detection:
  - Broadcasts {"_state": 7, "event": "<type>", "confidence": 0.0–1.0,
                "severity": 1–5, "severityLabel": "..."}
  - Inserts an alert_events document into MongoDB.

Pipeline:
  resample → buffer → queue copy of window → background worker runs PANNs.
  recv() never awaits inference so WebRTC keeps pulling frames (no multi‑second
  gaps on slow CPUs / VMs).
"""

import logging
import asyncio
import concurrent.futures
import time
from collections import deque
from datetime import datetime

import numpy as np
from av import AudioFrame
from aiortc import MediaStreamTrack

import db
from config import (
    PANN_CHUNK_SAMPLES,
    PANN_HOP_SAMPLES,
    PANN_INPUT_GAIN,
    PANN_SAMPLE_RATE,
    PANN_WINDOW_PEAK_GATE,
    PANN_WINDOW_PEAK_TARGET,
    COUGH_BURST_WINDOW_SEC,
    PANN_QUEUE_MAXSIZE,
    PANN_QUEUE_HIGH_WATERMARK,
)
from models import EventType
from services.domain_writes import write_child_status_event
from services.panns_respiratory import classify_respiratory_pann

logger   = logging.getLogger(__name__)
executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

def _run_background(coro, *, label: str) -> None:
    task = asyncio.create_task(coro)

    def _done(t: asyncio.Task) -> None:
        try:
            t.result()
        except Exception:
            logger.exception("Background task failed: %s", label)

    task.add_done_callback(_done)


# ── Audio resampling helper ───────────────────────────────────────────────────
def _resample(audio: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Resample to PANNs target rate (32 kHz) using scipy."""
    if src_rate == dst_rate:
        return audio
    from scipy.signal import resample as scipy_resample
    num_samples = int(len(audio) * dst_rate / src_rate)
    return scipy_resample(audio, num_samples).astype(np.float32)


# ── AudioTransformTrack ───────────────────────────────────────────────────────
class AudioTransformTrack(MediaStreamTrack):
    """
    WebRTC audio track that buffers frames and classifies respiratory sounds
    using PANNs (CNN14).
    """
    kind = "audio"

    def __init__(self, track, user_id: str, connections: dict,
                 globalvars: dict, session_id=None):
        super().__init__()
        self.track       = track
        self.user_id     = user_id
        self.connections = connections
        self.globalvars  = globalvars
        self.session_id  = session_id

        self._buffer: list[np.ndarray] = []
        self._buffer_samples = 0
        self._target_samples = PANN_CHUNK_SAMPLES

        self._respiratory_times: deque[float] = deque(maxlen=20)
        self._session_start: float = time.time()

        self._pann_queue: asyncio.Queue | None = None
        self._pann_worker_task: asyncio.Task | None = None
        self._pann_drop_log_ts: float = 0.0
        self._pann_skip_log_ts: float = 0.0

        logger.info("AudioTransformTrack (PANNs) created for user=%s", user_id)

    def _ensure_pann_worker(self) -> None:
        if self._pann_worker_task is not None and not self._pann_worker_task.done():
            return
        self._pann_queue = asyncio.Queue(maxsize=PANN_QUEUE_MAXSIZE)
        self._pann_worker_task = asyncio.create_task(self._pann_worker_loop())

    async def _pann_worker_loop(self) -> None:
        assert self._pann_queue is not None
        while True:
            try:
                waveform = await self._pann_queue.get()
            except asyncio.CancelledError:
                break
            if waveform is None:
                break
            try:
                if not self.globalvars.get("processing"):
                    continue
                now = time.time()
                cutoff = now - COUGH_BURST_WINDOW_SEC
                session_event_count = sum(1 for t in self._respiratory_times if t > cutoff)
                session_duration_s = max(now - self._session_start, 1.0)
                loop = asyncio.get_running_loop()

                def _run():
                    return classify_respiratory_pann(
                        waveform,
                        PANN_SAMPLE_RATE,
                        session_event_count=session_event_count,
                        session_duration_s=session_duration_s,
                    )

                event_key, conf, sev_level, sev_label = await loop.run_in_executor(
                    executor, _run,
                )

                if not event_key:
                    continue

                self._respiratory_times.append(now)
                logger.info(
                    "Respiratory event %s (conf=%.2f sev=%d/%s) user=%s",
                    event_key, conf, sev_level, sev_label, self.user_id,
                )

                payload = {
                    "_state":        7,
                    "event":         event_key,
                    "confidence":    round(conf, 2),
                    "severity":      sev_level,
                    "severityLabel": sev_label,
                }
                for ws in self.connections.values():
                    await ws.send_json(payload)

                try:
                    doc = {
                        "session_id": self.session_id,
                        "timestamp":  datetime.utcnow(),
                        "alert_type": event_key,
                        "confidence": round(conf, 2),
                        "metadata": {
                            "severity_level": sev_level,
                            "severity_label": sev_label,
                        },
                    }
                    await db.alert_events().insert_one(doc)
                    mapped_type = {
                        "cough": EventType.COUGH,
                        "sneeze": EventType.SNEEZE,
                    }.get(event_key)
                    if mapped_type is not None:
                        _run_background(
                            write_child_status_event(
                                globalvars=self.globalvars,
                                event_type=mapped_type,
                                confidence=round(conf, 2),
                                metadata={
                                    "source": "panns",
                                    "severity_level": sev_level,
                                    "severity_label": sev_label,
                                },
                            ),
                            label=f"child_status_events.{event_key}",
                        )
                except Exception:
                    logger.exception("Failed to log audio alert to MongoDB")
            except Exception:
                logger.exception("Error in PANNs worker")

    async def recv(self) -> AudioFrame:
        frame = await self.track.recv()

        # Only classify when session is active
        if not self.globalvars.get("processing"):
            if not hasattr(self, '_frame_count'):
                self._frame_count = 0
            self._frame_count += 1
            if self._frame_count % 200 == 0:
                logger.debug("Audio frames received (processing=False): %d user=%s",
                             self._frame_count, self.user_id)
            return frame

        try:
            self._ensure_pann_worker()

            # Convert av.AudioFrame → numpy float32 mono
            audio_np = frame.to_ndarray()
            if audio_np.ndim > 1:
                audio_np = audio_np.mean(axis=0)
            audio_np = audio_np.astype(np.float32)

            # Normalise to [-1.0, 1.0] if integer PCM
            if audio_np.max() > 1.0:
                audio_np = audio_np / 32768.0

            if PANN_INPUT_GAIN != 1.0:
                audio_np = np.clip(audio_np * float(PANN_INPUT_GAIN), -1.0, 1.0)

            # Resample to 32 kHz for PANNs
            audio_np = _resample(audio_np, frame.sample_rate, PANN_SAMPLE_RATE)

            # Accumulate into rolling buffer
            self._buffer.append(audio_np)
            self._buffer_samples += len(audio_np)

            # Once we have enough audio, classify (sliding window: keep tail after hop)
            if self._buffer_samples >= self._target_samples:
                full = np.concatenate(self._buffer)
                waveform = np.copy(full[: self._target_samples])
                hop = min(PANN_HOP_SAMPLES, self._target_samples - 1)
                tail = full[hop:]
                self._buffer = [tail] if len(tail) > 0 else []
                self._buffer_samples = len(tail)

                # Quiet 1 s windows (far mic): lift peak toward target so PANNs sees level
                # similar to “close mic” without changing loud windows (clipped after gain).
                if PANN_WINDOW_PEAK_GATE > 0 and PANN_WINDOW_PEAK_TARGET > 0:
                    peak = float(np.max(np.abs(waveform)))
                    if peak >= 1e-7 and peak < PANN_WINDOW_PEAK_GATE:
                        waveform = np.clip(
                            waveform * (PANN_WINDOW_PEAK_TARGET / peak),
                            -1.0,
                            1.0,
                        )

                logger.debug(
                    "Audio buffer full (%d samples, %.2f s) — queue PANNs",
                    len(waveform), len(waveform) / PANN_SAMPLE_RATE,
                )

                assert self._pann_queue is not None
                backlog = self._pann_queue.qsize()
                high_mark = max(1, int(PANN_QUEUE_MAXSIZE * PANN_QUEUE_HIGH_WATERMARK))
                if backlog >= high_mark:
                    t = time.time()
                    if t - self._pann_skip_log_ts > 5.0:
                        self._pann_skip_log_ts = t
                        logger.warning(
                            "PANNs backlog high (%d/%d) — skipping windows to keep realtime.",
                            backlog,
                            PANN_QUEUE_MAXSIZE,
                        )
                    return frame
                try:
                    self._pann_queue.put_nowait(waveform)
                except asyncio.QueueFull:
                    t = time.time()
                    if t - self._pann_drop_log_ts > 5.0:
                        self._pann_drop_log_ts = t
                        logger.warning(
                            "PANNs queue full (%d windows) — dropping audio windows; "
                            "increase CPU or raise PANN_HOP_FRACTION in config",
                            PANN_QUEUE_MAXSIZE,
                        )

        except Exception:
            logger.exception("Error in AudioTransformTrack.recv()")

        return frame
