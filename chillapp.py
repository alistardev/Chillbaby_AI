"""
chillapp.py – Application entrypoint.

All logic lives in routes/ and services/.
This file only wires routes, configures SSL, and starts the server.
"""

import asyncio
import json
import logging
import os
import ssl
import sys
import argparse
from datetime import datetime

import aiohttp_jinja2
import jinja2
from aiohttp import web

import config  # noqa: F401 – loads .env at import time
import db
from routes import webrtc, video, websocket, processing

# ── Shared mutable state ─────────────────────────────────────────────────────
connections: dict = {}          # { user_id: WebSocketResponse }
globalvars: dict  = {
    "processing":   False,
    "intolerances": [],
    "mainFood":     "",
    "filepath":     "",
    "filename":     "",
    "insertedId":   "",
    "video_url":    "",
    "alert_msg":    "",
    "processed":    False,
}

# ── App setup ────────────────────────────────────────────────────────────────
app = web.Application()
aiohttp_jinja2.setup(app, loader=jinja2.FileSystemLoader('templates'))

# ── Template routes ──────────────────────────────────────────────────────────

# GET / → show login screen (index.html) – no camera involved
@aiohttp_jinja2.template('index.html')
async def login_get(request):
    return {}


# POST /login → save user info, redirect to detection screen
async def login_post(request: web.Request) -> web.Response:
    data          = await request.post()
    parent_name   = data.get('parent_name', '').strip()
    email         = data.get('email', '').strip()
    company       = data.get('company', '').strip()
    intolerances  = [i.strip() for i in data.get('intolerances', '').split(',') if i.strip()]

    # Store in shared state so detection screen & processing routes can use them
    globalvars["intolerances"] = intolerances
    globalvars["parent_name"] = parent_name
    globalvars["parent_email"] = email
    globalvars["parent_company"] = company

    # Create the MongoDB session document upfront (camera starts later)
    new_session = {
        "name":         parent_name,
        "email":        email,
        "company":      company,
        "intolerances": intolerances,
        "started_at":   datetime.utcnow(),
        "video_link":   None,
    }
    try:
        result = await db.sessions().insert_one(new_session)
        globalvars["insertedId"] = result.inserted_id
        logging.getLogger(__name__).info(
            "Session created at login: id=%s user=%s", result.inserted_id, parent_name
        )
    except Exception:
        logging.getLogger(__name__).exception("Failed to insert session at login")

    # Redirect to the detection/process screen
    raise web.HTTPFound('/process')


# GET /process → main detection screen (camera opens here)
# Redirect to login if no session (user landed here directly or after restart)
@aiohttp_jinja2.template('process.html')
async def process_get(request):
    if not globalvars.get("insertedId"):
        raise web.HTTPFound('/')
    return {
        'alert_msg': '',
        'parent_name':    globalvars.get('parent_name', ''),
        'parent_email':   globalvars.get('parent_email', ''),
        'parent_company': globalvars.get('parent_company', ''),
        'intolerances_json': json.dumps(globalvars.get('intolerances', [])),
    }


async def view(request):
    import os
    content = open(os.path.join(os.path.dirname(__file__), "templates", "view.html")).read()
    return web.Response(content_type="text/html", text=content)


async def favicon(request):
    raise web.HTTPFound('/static/favicon.svg')

app.router.add_get('/',            login_get)
app.router.add_post('/login',      login_post)
app.router.add_get('/process',     process_get)
app.router.add_get('/view',        view)
app.router.add_get('/favicon.ico', favicon)
app.router.add_static('/static/', path='./static', name='static')

# ── Module routes ────────────────────────────────────────────────────────────
webrtc.setup_routes(app, connections, globalvars)
video.setup_routes(app, connections, globalvars)
websocket.setup_routes(app, connections, globalvars)
processing.setup_routes(app, connections, globalvars)

# ── Startup: load PANNs before any WebRTC audio enqueues (avoids queue overflow) ─
async def _startup_warm_panns(_app: web.Application) -> None:
    if os.environ.get("CAMMY_SKIP_PANN_WARMUP", "").strip().lower() in ("1", "true", "yes"):
        logging.getLogger(__name__).info("Skipping PANNs warmup (CAMMY_SKIP_PANN_WARMUP).")
        return
    from services.panns_respiratory import warmup_panns

    log = logging.getLogger(__name__)
    log.info("PANNs warmup starting (first install may download ~330 MB; then one inference)...")
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, warmup_panns)


app.on_startup.append(_startup_warm_panns)

# ── Shutdown hook ────────────────────────────────────────────────────────────
app.on_shutdown.append(webrtc.on_shutdown)


# ── Main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Chill Baby AI – AI child monitoring server")
    parser.add_argument("--cert-file", default="cert.pem")
    parser.add_argument("--key-file",  default="key.pem")
    parser.add_argument("--host",      default="0.0.0.0")
    parser.add_argument("--port",      type=int, default=5000)
    parser.add_argument("--verbose", "-v", action="count")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Windows: client closed tab / killed TCP → proactor cleanup calls shutdown() on a
    # dead socket and asyncio logs ERROR (WinError 10054). Harmless; hide unless debugging.
    if sys.platform == "win32" and os.environ.get("CAMMY_LOG_ASYNCIO_RESET", "").strip().lower() not in (
        "1", "true", "yes",
    ):

        class _SuppressAsyncioWin10054Filter(logging.Filter):
            def filter(self, record: logging.LogRecord) -> bool:
                if record.name != "asyncio":
                    return True
                ei = record.exc_info
                if ei and isinstance(ei[1], ConnectionResetError):
                    if getattr(ei[1], "winerror", None) == 10054:
                        return False
                return True

        logging.getLogger("asyncio").addFilter(_SuppressAsyncioWin10054Filter())

    ssl_context = None
    if args.cert_file and args.key_file:
        import os
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.load_cert_chain(
            os.path.join(os.getcwd(), args.cert_file),
            os.path.join(os.getcwd(), args.key_file),
        )

    web.run_app(app, access_log=None, host=args.host,
                port=args.port, ssl_context=ssl_context)
