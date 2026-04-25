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

import db
from services.food import send_frame_to_foodvisor

logger = logging.getLogger(__name__)


def setup_routes(app: web.Application, connections: dict, globalvars: dict):
    app.router.add_post('/startProcessing', lambda r: start_processing(r, connections, globalvars))
    app.router.add_post('/canvasImage',     lambda r: canvas_image(r, connections, globalvars))
    app.router.add_get('/final_page',       lambda r: final_page(r))


# ── /startProcessing ─────────────────────────────────────────────────────────
async def start_processing(request: web.Request,
                            connections: dict,
                            globalvars: dict) -> web.Response:
    data        = await request.json()
    username    = data.get('username', '')
    email       = data.get('email', '')
    companyname = data.get('companyname', '')
    intolerance = data.get('intolerance', [])

    globalvars["processing"] = True
    globalvars["intolerances"] = intolerance

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

    # Notify frontend
    name_str = f"name\\{username}\\{companyname}"
    for ws in connections.values():
        await ws.send_str(name_str)

    return web.Response()


# ── /canvasImage ──────────────────────────────────────────────────────────────
async def canvas_image(request: web.Request,
                        connections: dict,
                        globalvars: dict) -> web.Response:
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
