"""
Video upload / recording / streaming routes:
  POST /upload          – upload a video file for offline processing
  GET  /video_feed      – MJPEG stream of the processed video
  GET  /startRec        – create a new recording file path
  POST /uploadBlob      – append recording blob chunks to file
  GET  /endProcessing   – stop session, convert webm→mp4, update MongoDB
  GET  /static/videos/{filename} – download a recorded video
"""

import logging
import asyncio
import os
import subprocess
import concurrent.futures
from datetime import datetime
from tempfile import NamedTemporaryFile

import cv2
import numpy as np
from aiohttp import web
from scipy.spatial import distance as dist

from app_state import get_state
import db
from config import (
    STATIC_VIDEO_FOLDER,
    FFMPEG_PATH,
    EYE_AR_THRESH,
    EYE_AR_CONSEC_FRAMES,
)

logger   = logging.getLogger(__name__)
executor = concurrent.futures.ThreadPoolExecutor(max_workers=3)


def setup_routes(app: web.Application):
    app.router.add_post('/upload', upload_video)
    app.router.add_get('/video_feed', video_feed)
    app.router.add_get('/startRec', start_rec)
    app.router.add_post('/uploadBlob', upload_blob)
    app.router.add_get('/endProcessing', end_processing)
    app.router.add_get('/static/videos/{filename}', download_file)


# ── Helpers ──────────────────────────────────────────────────────────────────
def eye_aspect_ratio(eye) -> float:
    A = dist.euclidean(eye[1], eye[5])
    B = dist.euclidean(eye[2], eye[4])
    C = dist.euclidean(eye[0], eye[3])
    return (A + B) / (2.0 * C)


# ── Offline video generator (MJPEG) ─────────────────────────────────────────
async def gen(camera_path: str, globalvars: dict):
    """Async generator that processes an uploaded video file frame-by-frame."""
    isSleeping    = False
    sleepTrackList: list[float] = []
    awakeTrackList: list[float] = []
    COUNTER       = 0
    detect_flag   = False
    frame_count   = 0
    loop          = asyncio.get_event_loop()

    video              = cv2.VideoCapture(camera_path)
    original_frame_rate = video.get(cv2.CAP_PROP_FPS) or 15

    # mediapipe 0.10+ (Windows) no longer ships `mediapipe.solutions` — only newer Tasks API.
    face_mesh = None
    try:
        import mediapipe as mp
        if hasattr(mp, "solutions") and hasattr(mp.solutions, "face_mesh"):
            face_mesh = mp.solutions.face_mesh.FaceMesh(
                max_num_faces=1,
                refine_landmarks=True,
                min_detection_confidence=0.7,
                min_tracking_confidence=0.7,
            )
    except Exception as e:
        logger.warning(
            "MediaPipe legacy FaceMesh not available; sleep / EAR detection disabled in "
            "offline video stream (%s)",
            e,
        )

    try:
        while True:
            ret, frame = video.read()
            if not ret:
                break

            if face_mesh is not None and frame_count % 2 == 0:
                frame.flags.writeable = False
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                results = face_mesh.process(frame)
                frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                frame.flags.writeable = True

                if results.multi_face_landmarks:
                    for face_landmarks in results.multi_face_landmarks:
                        # Eye landmarks
                        left_eye_lms  = [face_landmarks.landmark[i] for i in [33,160,158,133,153,144]]
                        right_eye_lms = [face_landmarks.landmark[i] for i in [362,385,387,263,373,380]]

                        def pts(lm_list):
                            return [[int(l.x*frame.shape[1]), int(l.y*frame.shape[0])] for l in lm_list]

                        leftEye   = np.array(pts(left_eye_lms))
                        rightEye  = np.array(pts(right_eye_lms))
                        leftEAR   = eye_aspect_ratio(leftEye)
                        rightEAR  = eye_aspect_ratio(rightEye)
                        ear       = (leftEAR + rightEAR) / 2.0

                        if ear < EYE_AR_THRESH:
                            COUNTER += 1
                            if COUNTER >= EYE_AR_CONSEC_FRAMES and not detect_flag:
                                detect_flag = True
                                isSleeping  = True
                                cf = video.get(cv2.CAP_PROP_POS_FRAMES)
                                sleepTrackList.append(cf / original_frame_rate)
                        else:
                            COUNTER = 0
                            if isSleeping:
                                isSleeping  = False
                                detect_flag = False
                                cf = video.get(cv2.CAP_PROP_POS_FRAMES)
                                awakeTrackList.append(cf / original_frame_rate)

            encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 30]
            ok, buf = await loop.run_in_executor(executor, cv2.imencode, '.jpg', frame, encode_param)
            yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buf.tobytes() + b'\r\n'
            frame_count += 1
    finally:
        if face_mesh is not None:
            face_mesh.close()

    video.release()
    globalvars["processed"] = True
    logger.info("Offline video processing complete.")


# ── Route handlers ────────────────────────────────────────────────────────────
async def video_feed(request: web.Request) -> web.StreamResponse:
    globalvars = get_state(request).globalvars
    logger.info("video_feed requested")
    while not globalvars.get("video_url"):
        await asyncio.sleep(1)

    response = web.StreamResponse()
    response.content_type = 'multipart/x-mixed-replace; boundary=frame'
    await response.prepare(request)
    async for frame in gen(globalvars["video_url"], globalvars):
        await response.write(frame)
    globalvars["video_url"] = ""
    return response


async def upload_video(request: web.Request) -> web.Response:
    globalvars = get_state(request).globalvars
    logger.info("Video upload received")
    globalvars["video_url"] = ""
    globalvars["processed"] = False

    reader  = await request.multipart()
    file    = await reader.next()
    filestr = await file.read()

    with NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
        tmp.write(filestr)
        tmp.flush()
        globalvars["video_url"] = tmp.name

    while not globalvars.get("processed"):
        await asyncio.sleep(1)

    globalvars["processed"] = False
    return web.Response(text=globalvars.get("alert_msg", ""))


async def start_rec(request: web.Request) -> web.Response:
    globalvars = get_state(request).globalvars
    filename = datetime.now().strftime("%Y%m%d%H%M%S") + '.webm'
    filepath = os.path.join(STATIC_VIDEO_FOLDER, filename)
    globalvars["filepath"] = filepath
    globalvars["filename"] = filename
    logger.info("Recording started: %s", filepath)
    return web.Response(text="start recording")


async def upload_blob(request: web.Request) -> web.Response:
    globalvars = get_state(request).globalvars
    reader = await request.multipart()
    field  = await reader.next()
    if field.name != 'file':
        raise web.HTTPBadRequest(text="Expected field 'file'")

    size = 0
    if globalvars.get("filepath"):
        with open(globalvars["filepath"], 'ab') as f:
            while True:
                chunk = await field.read_chunk()
                if not chunk:
                    break
                size += len(chunk)
                f.write(chunk)
    logger.debug("Blob chunk written: %d bytes", size)
    return web.Response(text='successfully stored')


async def end_processing(request: web.Request) -> web.Response:
    state = get_state(request)
    connections = state.connections
    globalvars = state.globalvars
    globalvars["processing"] = False
    logger.info("End processing called")

    # Signal frontend recording ended
    for ws in connections.values():
        await ws.send_str("endRec\\endRecording")

    input_file = globalvars.get("filepath", "")
    video_link = "null"

    if input_file and os.path.exists(input_file):
        output_file = input_file.replace("webm", "mp4")
        cmd = [FFMPEG_PATH, '-i', input_file, output_file]
        try:
            subprocess.run(cmd, check=True)
            logger.info("FFmpeg conversion done: %s", output_file)
        except subprocess.CalledProcessError as e:
            logger.error("FFmpeg failed: %s", e)

        mp4_name   = globalvars["filename"].replace("webm", "mp4")
        video_link = f"https://mealtimecammy.com/static/videos/{mp4_name}"

        for ws in connections.values():
            await ws.send_str(f"endPro\\{mp4_name}")

    # Update MongoDB session record
    inserted_id = globalvars.get("insertedId")
    if inserted_id:
        try:
            await db.sessions().update_one(
                {"_id": inserted_id},
                {"$set": {"video_link": video_link, "ended_at": datetime.utcnow()}},
            )
        except Exception:
            logger.exception("Failed to update session video_link")

    globalvars["filepath"] = ""
    return web.Response(text="stopped processing")


async def download_file(request: web.Request) -> web.FileResponse:
    filename = request.match_info.get('filename', 'default.mp4')
    filepath = os.path.join(STATIC_VIDEO_FOLDER, filename)
    logger.info("Downloading file: %s", filepath)
    response = web.FileResponse(filepath)
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    return response
