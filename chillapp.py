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

from app_state import APP_STATE_KEY, AppState, get_state
import config  # noqa: F401 – loads .env at import time
import db
from services.domain_writes import create_or_update_meal_session_start
from routes import webrtc, video, websocket, processing, dashboard

# ── App setup ────────────────────────────────────────────────────────────────
app = web.Application()
app[APP_STATE_KEY] = AppState()
aiohttp_jinja2.setup(app, loader=jinja2.FileSystemLoader('templates'))

# ── Template routes ──────────────────────────────────────────────────────────

# GET / → show login screen (index.html) – no camera involved
@aiohttp_jinja2.template('index.html')
async def login_get(request):
    return {}


# POST /login → save user info, redirect to detection screen
async def login_post(request: web.Request) -> web.Response:
    state = get_state(request)
    globalvars = state.globalvars
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
        globalvars["mealSessionStartedAt"] = new_session["started_at"]

        # Persist the submitted start form explicitly for auditing/dashboard use.
        intake_doc = {
            "session_id": result.inserted_id,
            "name": parent_name,
            "email": email,
            "company": company,
            "intolerances": intolerances,
            "source": "index_login_form",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }
        intake_result = await db.intake_forms().insert_one(intake_doc)
        globalvars["intakeFormId"] = intake_result.inserted_id

        try:
            await create_or_update_meal_session_start(
                globalvars=globalvars,
                started_at=new_session["started_at"],
            )
        except Exception:
            logging.getLogger(__name__).exception("Failed additive meal_session write at login")
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
    state = get_state(request)
    globalvars = state.globalvars
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
webrtc.setup_routes(app)
video.setup_routes(app)
websocket.setup_routes(app)
processing.setup_routes(app)
dashboard.setup_routes(app)

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


async def _startup_seed_master_allergens(_app: web.Application) -> None:
    try:
        await db.ensure_collections_exist()
        inserted = await db.seed_master_allergens()
        await db.ensure_target_indexes()
        logging.getLogger(__name__).info(
            "master_allergens ready (inserted=%d)", inserted
        )
    except Exception:
        logging.getLogger(__name__).exception("Failed seeding master_allergens")


async def _startup_log_food_model_choice(_app: web.Application) -> None:
    try:
        from services.local_food_detector import get_local_food_model_selection

        selected = get_local_food_model_selection()
        logging.getLogger(__name__).info(
            "Local food model selected: %s", selected
        )
    except Exception:
        logging.getLogger(__name__).exception("Failed resolving local food model path")


app.on_startup.append(_startup_log_food_model_choice)
app.on_startup.append(_startup_seed_master_allergens)
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
