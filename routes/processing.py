"""
Processing routes:
  POST /startProcessing  – register user, begin session
  POST /canvasImage      – receive canvas frame, send to food recognition
  GET  /final_page       – end-of-session summary page (placeholder)
"""

import logging
from datetime import datetime

import numpy as np
import cv2
from aiohttp import web
import aiohttp_jinja2

from app_state import get_state
import db
from services.domain_writes import (
    create_or_update_meal_session_start,
    ensure_child_and_device_context,
)
from services.food import send_frame_to_foodvisor

logger = logging.getLogger(__name__)


def setup_routes(app: web.Application):
    app.router.add_post('/startProcessing', start_processing)
    app.router.add_post('/canvasImage', canvas_image)
    app.router.add_get('/final_page', final_page)


# ── /startProcessing ─────────────────────────────────────────────────────────
async def start_processing(request: web.Request) -> web.Response:
    state = get_state(request)
    connections = state.connections
    globalvars = state.globalvars
    data        = await request.json()
    username    = data.get('username', '')
    email       = data.get('email', '')
    companyname = data.get('companyname', '')
    intolerance = data.get('intolerance', [])

    globalvars["processing"] = True
    globalvars["intolerances"] = intolerance

    try:
        await ensure_child_and_device_context(globalvars=globalvars, payload=data)
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
    state = get_state(request)
    connections = state.connections
    globalvars = state.globalvars
    user_id = request.rel_url.query.get('token', '')

    reader = await request.multipart()
    field  = await reader.next()
    if field.name != 'photo':
        raise web.HTTPBadRequest(text="Expected field 'photo'")

    data  = await field.read(decode=True)
    nparr = np.frombuffer(data, np.uint8)
    frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    session_id = globalvars.get("insertedId")
    await send_frame_to_foodvisor(frame, user_id, connections, globalvars, session_id)
    return web.Response(text='Image received and processed.')


# ── /final_page ───────────────────────────────────────────────────────────────
async def final_page(request: web.Request) -> web.Response:
    logger.info("Final page requested")
    # scanner.html doesn't exist yet – return a placeholder response
    return web.Response(text="Session complete.", content_type="text/html")
