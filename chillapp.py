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
from datetime import datetime, timezone

import aiohttp_jinja2
import jinja2
from aiohttp import web

from app_state import (
    APP_STATE_KEY,
    AppState,
    clear_session_cookie,
    get_runtime_session,
    get_runtime_session_optional,
    get_state,
    has_tester_session,
    purge_idle_sessions,
    revoke_tester_session,
    set_session_cookie,
)
import config  # noqa: F401 – loads .env at import time
import db
from services.admin_auth import admin_configured, is_admin_authenticated, require_admin, require_tester_session
from services.children_access import count_active_children
from services.domain_writes import ensure_child_and_device_context
from services.ml_ready import ML_READY_KEY, MLReadyState, bootstrap_seconds
from routes import webrtc, video, websocket, processing, dashboard, children, testing, admin, session_api

# ── App setup ────────────────────────────────────────────────────────────────
app = web.Application()
app[APP_STATE_KEY] = AppState()
app[ML_READY_KEY] = MLReadyState()
aiohttp_jinja2.setup(app, loader=jinja2.FileSystemLoader('templates'))

# ── Template routes ──────────────────────────────────────────────────────────

async def _redirect_logged_in_tester(request: web.Request) -> None:
    """Send active testers away from the login page."""
    if not has_tester_session(request):
        return
    runtime = get_runtime_session_optional(request)
    assert runtime is not None
    globalvars = runtime.globalvars
    if not globalvars.get("childId"):
        admin_mode = is_admin_authenticated(request)
        child_count = await count_active_children(globalvars, admin_mode=admin_mode)
        if child_count == 0:
            raise web.HTTPFound("/children?setup=1")
        raise web.HTTPFound("/select-child")
    raise web.HTTPFound("/process")


def _dashboard_context(request: web.Request, *, admin_mode: bool) -> dict:
    runtime = get_runtime_session_optional(request)
    globalvars = runtime.globalvars if runtime else {}
    return {
        "parent_name": globalvars.get("parent_name", "") if not admin_mode else (globalvars.get("parent_name") or "Admin"),
        "admin_mode": admin_mode,
        "is_admin": is_admin_authenticated(request),
        "has_tester_session": has_tester_session(request),
    }


# GET / → show login screen (index.html) – no camera involved
@aiohttp_jinja2.template('index.html')
async def login_get(request):
    await _redirect_logged_in_tester(request)
    return {"consent_version": config.CAMMY_CONSENT_VERSION}


# POST /login → save caregiver info, then child setup or selection
async def login_post(request: web.Request) -> web.Response:
    from services.admin_auth import consent_accepted
    from services.tester_bootstrap import begin_tester_session

    data = await request.post()
    parent_name = data.get("parent_name", "").strip()
    email = data.get("email", "").strip().lower()
    company = data.get("company", "").strip()

    if not parent_name or not email:
        raise web.HTTPFound("/?err=missing")
    if not consent_accepted(data.get("consent")):
        raise web.HTTPFound("/?err=consent")

    try:
        token, _runtime = await begin_tester_session(
            get_state(request),
            parent_name=parent_name,
            email=email,
            company=company,
            source="index_login_form",
        )
    except Exception:
        logging.getLogger(__name__).exception("Failed to insert session at login")
        raise web.HTTPFound("/?err=database")

    child_count = await count_active_children(get_state(request).sessions[token].globalvars)
    next_url = "/children?setup=1" if child_count == 0 else "/select-child"
    resp = web.HTTPFound(next_url)
    set_session_cookie(resp, token)
    return resp


async def _redirect_if_no_session(globalvars: dict) -> None:
    if not globalvars.get("insertedId"):
        raise web.HTTPFound("/")


async def _redirect_if_no_child(request: web.Request, globalvars: dict) -> None:
    if not globalvars.get("childId"):
        admin_mode = is_admin_authenticated(request)
        child_count = await count_active_children(globalvars, admin_mode=admin_mode)
        if child_count == 0:
            raise web.HTTPFound("/children?setup=1")
        raise web.HTTPFound("/select-child")


# GET /select-child → pick child before monitoring
@aiohttp_jinja2.template("select-child.html")
async def select_child_get(request):
    runtime = get_runtime_session(request)
    globalvars = runtime.globalvars
    await _redirect_if_no_session(globalvars)
    admin_mode = is_admin_authenticated(request)
    child_count = await count_active_children(globalvars, admin_mode=admin_mode)
    if child_count == 0:
        raise web.HTTPFound("/children?setup=1")
    return {}


# POST /select-child → bind child to session, go to monitor
async def select_child_post(request: web.Request) -> web.Response:
    runtime = get_runtime_session(request)
    globalvars = runtime.globalvars
    await _redirect_if_no_session(globalvars)

    data = await request.post()
    child_id_raw = data.get("child_id", "").strip()
    if not child_id_raw:
        raise web.HTTPFound("/select-child?err=missing")

    payload = {"child_id": child_id_raw}
    try:
        await ensure_child_and_device_context(
            globalvars=globalvars,
            payload=payload,
            admin_mode=is_admin_authenticated(request),
        )
    except Exception:
        logging.getLogger(__name__).exception("Failed to bind child at select-child")
        raise web.HTTPFound("/select-child?err=invalid")

    if not globalvars.get("childId"):
        raise web.HTTPFound("/select-child?err=invalid")

    intolerances = globalvars.get("intolerances") or []
    session_id = globalvars.get("insertedId")
    try:
        if session_id:
            await db.sessions().update_one(
                {"_id": session_id},
                {
                    "$set": {
                        "child_id": globalvars.get("childId"),
                        "child_name": globalvars.get("child_name"),
                        "intolerances": intolerances,
                    }
                },
            )
        meal_session_id = globalvars.get("mealSessionId")
        if meal_session_id:
            await db.meal_sessions().update_one(
                {"_id": meal_session_id},
                {
                    "$set": {
                        "child_id": globalvars.get("childId"),
                        "updated_at": datetime.now(timezone.utc),
                    }
                },
            )
    except Exception:
        logging.getLogger(__name__).exception("Failed to update session with child_id")

    raise web.HTTPFound("/process")


# GET /process → main detection screen (camera opens here)
# Redirect to login if no session (user landed here directly or after restart)
@aiohttp_jinja2.template('process.html')
async def process_get(request):
    runtime = get_runtime_session(request)
    globalvars = runtime.globalvars
    await _redirect_if_no_session(globalvars)
    await _redirect_if_no_child(request, globalvars)
    return {
        'alert_msg': '',
        'parent_name':    globalvars.get('parent_name', ''),
        'parent_email':   globalvars.get('parent_email', ''),
        'parent_company': globalvars.get('parent_company', ''),
        'child_name':     globalvars.get('child_name', ''),
        'child_id':       str(globalvars.get('childId') or ''),
        'intolerances_json': json.dumps(globalvars.get('intolerances', [])),
        'food_capture_interval_ms': int(config.FOOD_CAPTURE_INTERVAL_S * 1000),
        'food_capture_change_min_ms': int(config.FOOD_CAPTURE_CHANGE_MIN_S * 1000),
        'stream_food_from_video': config.STREAM_FOOD_FROM_VIDEO,
        'food_canvas_max_dim': config.FOOD_CANVAS_MAX_DIM,
        'detection_bootstrap_ms': int(bootstrap_seconds() * 1000) + 800,
        'is_admin': is_admin_authenticated(request),
    }


# GET /children → child profile management (Phase 8.1)
@aiohttp_jinja2.template('children.html')
async def children_get(request):
    runtime = get_runtime_session_optional(request)
    globalvars = runtime.globalvars if runtime else {}
    setup = request.query.get("setup") in ("1", "true", "yes")
    if setup:
        await _redirect_if_no_session(globalvars)
    elif not has_tester_session(request):
        raise web.HTTPFound("/")
    return {
        "setup_mode": setup,
        "is_admin": is_admin_authenticated(request),
    }


# GET /dashboard → tester's own session history
@aiohttp_jinja2.template('dashboard.html')
async def dashboard_get(request):
    require_tester_session(request)
    return _dashboard_context(request, admin_mode=False)


# GET /admin/dashboard → all testers (admin only)
@aiohttp_jinja2.template('dashboard.html')
async def admin_dashboard_get(request):
    require_admin(request)
    return _dashboard_context(request, admin_mode=True)


async def tester_logout_post(request: web.Request) -> web.Response:
    revoke_tester_session(request)
    resp = web.HTTPFound("/")
    clear_session_cookie(resp)
    return resp


async def view(request):
    import os
    content = open(os.path.join(os.path.dirname(__file__), "templates", "view.html")).read()
    return web.Response(content_type="text/html", text=content)


async def favicon(request):
    raise web.HTTPFound('/static/favicon.svg')

app.router.add_get('/',            login_get)
app.router.add_post('/login',      login_post)
app.router.add_get('/select-child', select_child_get)
app.router.add_post('/select-child', select_child_post)
app.router.add_get('/process',     process_get)
app.router.add_get('/children',    children_get)
app.router.add_get('/dashboard',   dashboard_get)
app.router.add_get('/admin/dashboard', admin_dashboard_get)
app.router.add_post('/logout',     tester_logout_post)
app.router.add_get('/view',        view)
app.router.add_get('/favicon.ico', favicon)
app.router.add_static('/static/', path='./static', name='static')

# ── Module routes ────────────────────────────────────────────────────────────
webrtc.setup_routes(app)
video.setup_routes(app)
websocket.setup_routes(app)
processing.setup_routes(app)
dashboard.setup_routes(app)
children.setup_routes(app)
testing.setup_routes(app)
admin.setup_routes(app)
session_api.setup_routes(app)

# ── Startup: load PANNs before any WebRTC audio enqueues (avoids queue overflow) ─
async def _startup_log_admin(_app: web.Application) -> None:
    log = logging.getLogger(__name__)
    if admin_configured():
        log.info("Admin dashboard auth enabled (user=%s).", config.CAMMY_ADMIN_USERNAME)
    else:
        log.warning(
            "CAMMY_ADMIN_USERNAME / CAMMY_ADMIN_PASSWORD not set — /dashboard is locked until configured."
        )


async def _startup_log_profile(_app: web.Application) -> None:
    log = logging.getLogger(__name__)
    log.info(
        "Runtime profile: CAMMY_PROFILE=%s (cuda=%s) — emotion=%ss bootstrap=%ss canvas=%spx food_imgsz=%s",
        config.CAMMY_PROFILE,
        config._ON_CUDA,
        config.EMOTION_INTERVAL_S,
        bootstrap_seconds(),
        config.FOOD_CANVAS_MAX_DIM,
        config.LOCAL_FOOD_PREDICT_IMGSZ,
    )


async def _startup_warm_ml(_app: web.Application) -> None:
    """Load food YOLO, FER, and child YOLO in parallel before first live session."""
    from datetime import datetime, timezone

    ready = _app[ML_READY_KEY]
    if config.CAMMY_SKIP_ML_WARMUP:
        ready.ml_skipped = True
        ready.updated_at = datetime.now(timezone.utc)
        logging.getLogger(__name__).info("Skipping ML warmup (CAMMY_SKIP_ML_WARMUP).")
        return

    from services.child_detector import warmup_child_yolo
    from services.emotion import warmup_fer
    from services.local_food_detector import warmup_food_yolo

    log = logging.getLogger(__name__)
    log.info("ML warmup starting (FER first, then food + child YOLO)...")
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, warmup_fer)
        await asyncio.gather(
            loop.run_in_executor(None, warmup_food_yolo),
            loop.run_in_executor(None, warmup_child_yolo),
        )
        ready.ml_warmup_done = True
        ready.updated_at = datetime.now(timezone.utc)
        log.info("ML warmup done.")
    except Exception as exc:
        ready.ml_error = str(exc)
        ready.updated_at = datetime.now(timezone.utc)
        log.exception("ML warmup failed")


async def _startup_warm_panns(_app: web.Application) -> None:
    from datetime import datetime, timezone

    log = logging.getLogger(__name__)
    ready = _app[ML_READY_KEY]
    if config.CAMMY_SKIP_PANN_WARMUP:
        ready.panns_skipped = True
        ready.updated_at = datetime.now(timezone.utc)
        log.warning(
            "CAMMY_SKIP_PANN_WARMUP=1 — PANNs loads on first audio (adds CPU spike + food delay). "
            "Set CAMMY_SKIP_PANN_WARMUP=0 on CPU servers."
        )
        return
    from services.panns_respiratory import warmup_panns

    log.info("PANNs warmup starting (first install may download ~330 MB; then one inference)...")
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, warmup_panns)
        ready.panns_warmup_done = True
        ready.updated_at = datetime.now(timezone.utc)
    except Exception as exc:
        ready.panns_error = str(exc)
        ready.updated_at = datetime.now(timezone.utc)
        log.exception("PANNs warmup failed")


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


async def _startup_load_allergen_map(_app: web.Application) -> None:
    try:
        from services.allergen_lookup import preload_allergen_cache

        preload_allergen_cache()
    except Exception:
        logging.getLogger(__name__).exception("Failed loading allergen map")


async def _startup_log_food_model_choice(_app: web.Application) -> None:
    try:
        from services.local_food_detector import (
            describe_food_model_file,
            get_local_food_model_selection,
            reset_food_model_cache,
            validate_food_model_file,
        )
        from services.food import reset_clarifai_for_new_session

        reset_food_model_cache()
        reset_clarifai_for_new_session()
        selected = get_local_food_model_selection()
        log = logging.getLogger(__name__)
        log.info("Local food model path: %s (%s)", selected, describe_food_model_file(selected))
        ok, detail = validate_food_model_file(selected)
        if not ok:
            log.warning(
                "Food weights problem at %s — %s. COCO + Clarifai until fixed.",
                selected,
                detail,
            )
        else:
            log.info("Food weights file: %s", detail)
        log.info(
            "Food detection: FOOD_PROVIDER=%s | Clarifai=%s",
            config.FOOD_PROVIDER,
            "on" if config.FOOD_PROVIDER in ("auto", "hybrid", "api") else "off",
        )
    except Exception:
        logging.getLogger(__name__).exception("Failed resolving local food model path")


async def _startup_sync_food_model(_app: web.Application) -> None:
    """Copy ``.pt`` from prepare_food_dataset when destination missing (see config)."""
    if not getattr(config, "CAMMY_AUTO_SYNC_FOOD_MODEL", True):
        return
    try:
        from services.food_model_sync import sync_food_model_if_missing

        sync_food_model_if_missing()
    except Exception:
        logging.getLogger(__name__).exception("Food model auto-sync failed")


app.on_startup.insert(0, _startup_sync_food_model)
app.on_startup.insert(1, _startup_log_admin)
app.on_startup.insert(2, _startup_log_profile)
app.on_startup.append(_startup_log_food_model_choice)
app.on_startup.append(_startup_warm_ml)
app.on_startup.append(_startup_seed_master_allergens)
app.on_startup.append(_startup_load_allergen_map)
app.on_startup.append(_startup_warm_panns)


async def _session_idle_cleanup_loop(app: web.Application) -> None:
    async def _loop() -> None:
        while True:
            await asyncio.sleep(3600)
            removed = purge_idle_sessions(app[APP_STATE_KEY])
            if removed:
                logging.getLogger(__name__).info("Purged %s idle tester session(s)", removed)

    app["_session_cleanup_task"] = asyncio.create_task(_loop())


async def _session_idle_cleanup_shutdown(app: web.Application) -> None:
    task = app.pop("_session_cleanup_task", None)
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app.on_startup.append(_session_idle_cleanup_loop)
app.on_cleanup.append(_session_idle_cleanup_shutdown)

# ── Shutdown hook ────────────────────────────────────────────────────────────
async def _on_app_shutdown(app: web.Application) -> None:
    await db.close_client()


app.on_shutdown.append(webrtc.on_shutdown)
app.on_shutdown.append(_on_app_shutdown)


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
