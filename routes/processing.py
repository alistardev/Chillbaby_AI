"""
Processing routes:
  POST /startProcessing  – register user, begin session
  POST /canvasImage      – receive canvas frame, send to food recognition
  GET  /final_page       – end-of-session summary page (placeholder)
"""

import asyncio
import logging
import time
from datetime import datetime

import numpy as np
import cv2
from aiohttp import web
import aiohttp_jinja2

from app_state import get_runtime_session, get_session_token
from services.admin_auth import is_admin_authenticated
import db
from config import FOOD_CANVAS_MAX_DIM
from services.domain_writes import (
    create_or_update_meal_session_start,
    ensure_child_and_device_context,
)
from services.food import clear_food_client_state, reset_food_runtime_state, send_frame_to_foodvisor

logger = logging.getLogger(__name__)


def _resize_frame_for_food(bgr: np.ndarray) -> np.ndarray:
    """Cap long edge before YOLO — matches browser canvas scale, saves CPU."""
    h, w = bgr.shape[:2]
    m = max(h, w)
    if m <= FOOD_CANVAS_MAX_DIM:
        return bgr
    scale = FOOD_CANVAS_MAX_DIM / m
    nw = max(1, int(round(w * scale)))
    nh = max(1, int(round(h * scale)))
    return cv2.resize(bgr, (nw, nh), interpolation=cv2.INTER_LINEAR)


def setup_routes(app: web.Application):
    app.router.add_post('/startProcessing', start_processing)
    app.router.add_post('/canvasImage', canvas_image)
    app.router.add_get('/final_page', final_page)


# ── /startProcessing ─────────────────────────────────────────────────────────
async def start_processing(request: web.Request) -> web.Response:
    runtime = get_runtime_session(request)
    connections = runtime.connections
    globalvars = runtime.globalvars
    data        = await request.json()
    username    = data.get('username', '')
    email       = data.get('email', '')
    companyname = data.get('companyname', '')
    intolerance = data.get('intolerance', [])

    globalvars["processing"] = True
    globalvars["intolerances"] = intolerance
    globalvars["personPresent"] = None
    globalvars["processing_started_mono"] = time.monotonic()
    globalvars["_fer_first_result"] = False
    globalvars["_fer_active"] = False
    runtime_key = get_session_token(request) or str(globalvars.get("insertedId") or "")
    globalvars["runtimeSessionKey"] = runtime_key
    reset_food_runtime_state(runtime_key)
    clear_food_client_state(runtime.connections.keys())

    payload = dict(data)
    if not payload.get("child_id") and globalvars.get("childId"):
        payload["child_id"] = str(globalvars["childId"])
    if not payload.get("child_name") and globalvars.get("child_name"):
        payload["child_name"] = globalvars["child_name"]

    try:
        await ensure_child_and_device_context(
            globalvars=globalvars,
            payload=payload,
            admin_mode=is_admin_authenticated(request),
        )
    except Exception:
        logger.exception("Failed to resolve child/device context")

    existing_id = globalvars.get("insertedId")
    try:
        if existing_id:
            await db.sessions().update_one(
                {"_id": existing_id},
                {"$set": {"intolerances": intolerance}},
            )
            logger.info("Monitoring started (existing session id=%s)", existing_id)
        else:
            new_session = {
                "tester_id":    globalvars.get("testerId"),
                "name":         username,
                "email":        email,
                "company":      companyname,
                "intolerances": intolerance,
                "started_at":   datetime.utcnow(),
                "video_link":   None,
            }
            result = await db.sessions().insert_one(new_session)
            globalvars["insertedId"] = result.inserted_id
            logger.info("Session created: id=%s user=%s", result.inserted_id, username)
    except Exception:
        logger.exception("Failed to save session in MongoDB")

    try:
        await db.intake_forms().update_one(
            {"session_id": globalvars.get("insertedId")},
            {
                "$set": {
                    "name": username,
                    "email": email,
                    "company": companyname,
                    "intolerances": intolerance,
                    "last_start_processing_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow(),
                },
                "$setOnInsert": {
                    "session_id": globalvars.get("insertedId"),
                    "source": "start_processing_payload",
                    "created_at": datetime.utcnow(),
                },
            },
            upsert=True,
        )
    except Exception:
        logger.exception("Failed to upsert intake form record")

    # Additive write to new logical anchor collection (non-breaking if it fails).
    try:
        start_ts = datetime.utcnow()
        globalvars["mealSessionStartedAt"] = start_ts
        await create_or_update_meal_session_start(globalvars=globalvars, started_at=start_ts)
    except Exception:
        logger.exception("Failed additive meal_session start write")

    # Notify frontend
    name_str = f"name\\{username}\\{companyname}"
    for ws in connections.values():
        await ws.send_str(name_str)

    return web.Response()


# ── /canvasImage ──────────────────────────────────────────────────────────────
async def canvas_image(request: web.Request) -> web.Response:
    runtime = get_runtime_session(request)
    connections = runtime.connections
    globalvars = runtime.globalvars
    user_id = request.rel_url.query.get('token', '')
    food_user_id = (
        str(globalvars.get("runtimeSessionKey") or "")
        or get_session_token(request)
        or user_id
    )

    reader = await request.multipart()
    field  = await reader.next()
    if field.name != 'photo':
        raise web.HTTPBadRequest(text="Expected field 'photo'")

    data  = await field.read(decode=True)
    nparr = np.frombuffer(data, np.uint8)
    frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if frame is None:
        logger.warning("canvasImage: JPEG decode failed (token=%s)", (user_id or "")[:12])
        return web.Response(text="Invalid image", status=400)

    frame = _resize_frame_for_food(frame)
    session_id = globalvars.get("insertedId")
    asyncio.create_task(
        send_frame_to_foodvisor(frame, food_user_id, connections, globalvars, session_id)
    )
    return web.Response(text="accepted", status=202)


# ── /final_page ───────────────────────────────────────────────────────────────
async def final_page(request: web.Request) -> web.Response:
    logger.info("Final page requested")
    # scanner.html doesn't exist yet – return a placeholder response
    return web.Response(text="Session complete.", content_type="text/html")
