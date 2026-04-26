"""
WebSocket routes: /chill_results  and  /chill_view
"""

import logging
import aiohttp
from aiohttp import web

from app_state import get_state

logger = logging.getLogger(__name__)


def setup_routes(app: web.Application):
    app.router.add_get('/chill_results', websocket_handler, name='results')
    app.router.add_get('/chill_view', websocket_view_handler)


# ── /chill_results – per-user results WebSocket (presenter) ─────────────────
async def websocket_handler(request: web.Request,
                            ) -> web.WebSocketResponse:
    state = get_state(request)
    connections = state.connections
    globalvars = state.globalvars
    user_id = request.rel_url.query.get('token', '')
    logger.info("WebSocket connected: user=%s", user_id)

    # Clear food UI state only. Do NOT set processing=False here: a reconnect after
    # /startProcessing would silently disable PANNs cough/sneeze detection while
    # WebRTC audio is still running (AudioTransformTrack checks globalvars["processing"]).
    globalvars["mainFood"] = ""

    ws = web.WebSocketResponse()
    await ws.prepare(request)
    connections[user_id] = ws

    try:
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.ERROR:
                logger.warning("WS error for user=%s: %s", user_id, ws.exception())
    except ConnectionResetError:
        logger.info("WS connection reset by client: user=%s", user_id)
    finally:
        connections.pop(user_id, None)
        globalvars["processing"] = False
        await ws.close()
        logger.info("WebSocket closed: user=%s", user_id)

    return ws


# ── /chill_view – viewer WebSocket ──────────────────────────────────────────
async def websocket_view_handler(request: web.Request,
                                 ) -> web.WebSocketResponse:
    state = get_state(request)
    connections = state.connections
    user_id = request.rel_url.query.get('token', '')
    logger.info("Viewer WebSocket connected: user=%s", user_id)

    ws = web.WebSocketResponse()
    await ws.prepare(request)
    connections[user_id] = ws

    try:
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.ERROR:
                logger.warning("Viewer WS error: %s", ws.exception())
    except ConnectionResetError:
        logger.info("Viewer WS reset: user=%s", user_id)
    finally:
        connections.pop(user_id, None)
        await ws.close()
        logger.info("Viewer WebSocket closed: user=%s", user_id)

    return ws
