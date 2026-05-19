"""
Food recognition & intolerance checking.

Pipeline (full camera frame — child and food anywhere in view):
  1. Local YOLO (food_detector.pt), optional COCO yolov8m when primary misses
  2. Clarifai only as fallback when local is empty/weak (saves API credits)
"""

from __future__ import annotations

import logging
import asyncio
import time
from datetime import datetime
from typing import Any

import cv2

import db
from config import (
    CLARIFAI_APP_ID,
    CLARIFAI_FALLBACK_ONLY,
    CLARIFAI_MERGE_EVERY_FRAME,
    CLARIFAI_MIN_CONFIDENCE,
    CLARIFAI_MIN_INTERVAL_S,
    CLARIFAI_SKIP_IF_LOCAL_CONF,
    CLARIFAI_USER_ID,
    FOOD_API_KEY,
    FOOD_API_KEY_2,
    FOOD_PROVIDER,
    FOOD_MIN_CONFIDENCE,
    FOOD_MIN_INTERVAL_S,
    FOOD_CLEAR_DEBOUNCE_S,
    MODEL_ID,
    MODEL_VERSION_ID,
)
from services.local_food_detector import detect_food_local, friendly_food_label, get_food_executor
from services.domain_writes import write_food_diary_and_allergen_log
from services.emotion import get_max_emotion
from services.nutrition import broadcast_nutrition_clear, nutrition_info

logger = logging.getLogger(__name__)
_last_food_emit_ts: dict[str, float] = {}
_last_food_emit_main: dict[str, str] = {}
_last_clarifai_ts: dict[str, float] = {}

_clarifai_stub: Any = None
_clarifai_metadata_primary: tuple | None = None
_clarifai_metadata_fallback: tuple | None = None
_active_clarifai_metadata: tuple | None = None
_clarifai_disabled: bool = False
_clarifai_last_error_log: float = 0.0
# Public Clarifai models (e.g. general-image-recognition) live under clarifai/main.
_CLARIFAI_PUBLIC_USER = "clarifai"
_CLARIFAI_PUBLIC_APP = "main"

# Clarifai concepts must match this list (Chill-baby-style whitelist).
_FOOD_WHITELIST = frozenset({
    "apple", "banana", "orange", "mango", "grape", "grapes", "strawberry",
    "strawberries", "blueberry", "blueberries", "raspberry", "raspberries",
    "watermelon", "pineapple", "kiwi", "lemon", "lime", "peach", "pear",
    "apricot", "cherry", "cherries", "plum", "plums", "fig", "figs", "dates",
    "pomegranate", "nectarine", "berries", "blackberry", "melon", "papaya",
    "coconut", "avocado", "grapefruit",
    "broccoli", "carrot", "tomato", "cucumber", "spinach", "lettuce",
    "onion", "garlic", "potato", "sweet potato", "corn", "peas", "pumpkin",
    "zucchini", "eggplant", "cauliflower", "mushroom", "mushrooms",
    "celery", "asparagus", "cabbage", "beetroot", "bell pepper",
    "almond", "almonds", "walnut", "peanut", "cashew", "hazelnut",
    "pistachio", "pecan", "pine nuts", "mixed nuts", "sesame seeds",
    "milk", "cheese", "yogurt", "butter", "cream", "mozzarella",
    "parmesan", "feta", "cheddar", "cottage cheese",
    "chicken", "beef", "pork", "lamb", "salmon", "tuna", "fish", "shrimp",
    "egg", "bacon", "ham", "sausage", "salami", "steak",
    "rice", "pasta", "bread", "pizza", "sandwich", "burger", "hamburger",
    "noodles", "oats", "cereal", "croissant", "waffle", "pancake",
    "toast", "muffin", "cookie", "cookies", "cake", "donut", "brownie",
    "cracker", "chips", "fries", "french fries",
    "coffee", "tea", "juice", "smoothie", "water",
    "chocolate", "dark chocolate", "ice cream", "soup", "salad",
    "hummus", "guacamole", "peanut butter", "honey", "jam", "sushi",
    "curry", "tofu", "lentils", "chickpeas", "beans", "quinoa",
    "hot dog",
})

# COCO yolov8m often labels hand-held fruit/bread as these — downrank when picking main food.
_GENERIC_COCO_FOODS = frozenset({"sandwich", "hot dog", "cake", "donut"})
_GENERIC_SCORE_FACTOR = {
    "sandwich": 0.48,
    "hot dog": 0.55,
    "cake": 0.58,
    "donut": 0.62,
}


def _adjusted_food_score(name: str, confidence: float) -> float:
    return float(confidence) * _GENERIC_SCORE_FACTOR.get(name, 1.0)


def pick_main_food(
    merged: dict[str, float],
    *,
    clarifai: dict[str, float] | None = None,
) -> str:
    """
    Choose display food — not raw max confidence (sandwich false positives on hand-held items).
    """
    if not merged:
        return ""

    ranked = sorted(
        merged.items(),
        key=lambda item: -_adjusted_food_score(item[0], item[1]),
    )
    main = ranked[0][0]

    if clarifai and main in _GENERIC_COCO_FOODS:
        cf_best = max(clarifai, key=clarifai.get)
        if (
            cf_best not in _GENERIC_COCO_FOODS
            and float(clarifai[cf_best]) >= CLARIFAI_MIN_CONFIDENCE
        ):
            return cf_best

    for name, conf in ranked:
        if name not in _GENERIC_COCO_FOODS and float(conf) >= FOOD_MIN_CONFIDENCE:
            return name

    # Only generic labels (e.g. sandwich) — still show best if above UI threshold
    if float(ranked[0][1]) >= FOOD_MIN_CONFIDENCE:
        return main
    return ""


def merge_food_results(*sources: dict[str, float]) -> dict[str, float]:
    merged: dict[str, float] = {}
    for src in sources:
        for name, conf in src.items():
            try:
                c = float(conf)
            except Exception:
                continue
            key = friendly_food_label(name) or name.lower().strip()
            if key:
                merged[key] = max(merged.get(key, 0.0), round(c, 2))
    return merged


def _get_clarifai_stub():
    global _clarifai_stub, _clarifai_metadata_primary, _clarifai_metadata_fallback
    global _active_clarifai_metadata
    if not FOOD_API_KEY.strip() or not MODEL_ID.strip():
        return None, None
    if _clarifai_stub is None:
        from clarifai_grpc.channel.clarifai_channel import ClarifaiChannel
        from clarifai_grpc.grpc.api import service_pb2_grpc

        _clarifai_metadata_primary = (("authorization", "Key " + FOOD_API_KEY),)
        if FOOD_API_KEY_2.strip():
            _clarifai_metadata_fallback = (("authorization", "Key " + FOOD_API_KEY_2),)
        _active_clarifai_metadata = _clarifai_metadata_primary
        channel = ClarifaiChannel.get_grpc_channel()
        _clarifai_stub = service_pb2_grpc.V2Stub(channel)
    return _clarifai_stub, _active_clarifai_metadata


def _parse_clarifai_response(response) -> dict[str, float]:
    from clarifai_grpc.grpc.api.status import status_code_pb2

    if response.status.code != status_code_pb2.SUCCESS:
        return {}
    raw: dict[str, float] = {}
    for concept in response.outputs[0].data.concepts:
        conf = float(concept.value)
        if conf < CLARIFAI_MIN_CONFIDENCE:
            continue
        name = concept.name.lower().strip()
        if name in _FOOD_WHITELIST:
            raw[name] = round(conf, 2)
    return raw


def _clarifai_user_app_sets() -> list[tuple[str, str]]:
    """Try configured app first, then public clarifai/main for shared models."""
    primary = (CLARIFAI_USER_ID.strip(), CLARIFAI_APP_ID.strip())
    sets: list[tuple[str, str]] = []
    if primary[0] and primary[1]:
        sets.append(primary)
    public = (_CLARIFAI_PUBLIC_USER, _CLARIFAI_PUBLIC_APP)
    if public not in sets:
        sets.append(public)
    return sets


def _log_clarifai_error_once(msg: str, *args) -> None:
    global _clarifai_last_error_log
    now = time.monotonic()
    if now - _clarifai_last_error_log >= 30.0:
        _clarifai_last_error_log = now
        logger.warning(msg, *args)


def _concepts_json_to_food(concepts: list) -> dict[str, float]:
    raw: dict[str, float] = {}
    for concept in concepts:
        if isinstance(concept, dict):
            conf = float(concept.get("value", 0))
            name = str(concept.get("name", "")).lower().strip()
        else:
            conf = float(concept.value)
            name = str(concept.name).lower().strip()
        if conf < CLARIFAI_MIN_CONFIDENCE:
            continue
        if name in _FOOD_WHITELIST:
            raw[name] = round(conf, 2)
    return raw


def _call_clarifai_rest(frame_bytes: bytes, api_key: str, user_id: str, app_id: str) -> dict[str, float]:
    """HTTPS REST predict — works when gRPC fails (common on Windows with a bad http_proxy)."""
    import base64
    import json
    import urllib.error
    import urllib.request

    url = f"https://api.clarifai.com/v2/models/{MODEL_ID}/outputs"
    payload: dict[str, Any] = {
        "user_app_id": {"user_id": user_id, "app_id": app_id},
        "inputs": [{"data": {"image": {"base64": base64.b64encode(frame_bytes).decode("ascii")}}}],
    }
    if MODEL_VERSION_ID:
        payload["version_id"] = MODEL_VERSION_ID

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Key {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:300]
        _log_clarifai_error_once("Clarifai REST HTTP %s (%s/%s): %s", e.code, user_id, app_id, detail)
        return {}
    except Exception as e:
        _log_clarifai_error_once("Clarifai REST failed (%s/%s): %s", user_id, app_id, e)
        return {}

    status = body.get("status") or {}
    if int(status.get("code", 0)) != 10000:
        _log_clarifai_error_once(
            "Clarifai REST %s/%s: %s",
            user_id,
            app_id,
            status.get("description", status),
        )
        return {}

    outputs = body.get("outputs") or []
    if not outputs:
        return {}
    concepts = (outputs[0].get("data") or {}).get("concepts") or []
    return _concepts_json_to_food(concepts)


def _call_clarifai(frame_bytes: bytes) -> dict[str, float]:
    """Clarifai via REST (gRPC often returns PERMISSION_DENIED on this machine)."""
    if _clarifai_disabled:
        return {}

    keys: list[str] = []
    if FOOD_API_KEY.strip():
        keys.append(FOOD_API_KEY.strip())
    if FOOD_API_KEY_2.strip() and FOOD_API_KEY_2.strip() not in keys:
        keys.append(FOOD_API_KEY_2.strip())
    if not keys:
        return {}

    for api_key in keys:
        for user_id, app_id in _clarifai_user_app_sets():
            raw = _call_clarifai_rest(frame_bytes, api_key, user_id, app_id)
            if raw:
                top = max(raw, key=raw.get)
                logger.info("[FOOD] Clarifai (REST): %s (%.2f) | %s", top, raw[top], raw)
                return raw

    _log_clarifai_error_once(
        "Clarifai REST: no whitelisted food (MODEL_ID=%s, min_conf=%.2f)",
        MODEL_ID,
        CLARIFAI_MIN_CONFIDENCE,
    )
    return {}


def check_substrings(s: str, substrings: list) -> bool:
    return any(sub in s for sub in substrings)


async def intol_processing(main_food: str, intolerances: list, connections: dict) -> None:
    logger.info("Intolerance check: food=%s intolerances=%s", main_food, intolerances)
    answer = "yes" if check_substrings(main_food, intolerances) else "no"
    payload = {"_state": 4, "result": answer}
    for ws in connections.values():
        await ws.send_json(payload)


async def _send_food_ws(user_id: str, connections: dict, payload: dict) -> None:
    ws_one = connections.get(user_id)
    if ws_one is not None:
        await ws_one.send_json(payload)
        return
    if connections:
        logger.warning(
            "Food emit: no WebSocket for token=%s; broadcasting to %d connection(s)",
            (user_id or "")[:16],
            len(connections),
        )
    for ws in connections.values():
        await ws.send_json(payload)


def _filter_for_ui(food_list: dict[str, float]) -> dict[str, float]:
    out: dict[str, float] = {}
    for name, score in food_list.items():
        try:
            s = float(score)
        except Exception:
            continue
        min_conf = FOOD_MIN_CONFIDENCE
        if name == "unknown_food":
            min_conf = max(0.08, FOOD_MIN_CONFIDENCE * 0.66)
        if s >= min_conf:
            out[name] = s
    return out


def _local_best_confidence(local_foods: dict[str, float]) -> float:
    ui = _filter_for_ui(local_foods)
    if not ui:
        return 0.0
    return max(float(v) for v in ui.values())


def _clarifai_skip_reason(
    user_id: str,
    local_foods: dict[str, float],
    *,
    now: float,
) -> str | None:
    """None = call Clarifai; otherwise human-readable skip reason."""
    if _clarifai_disabled:
        return "disabled for this session (restart server to retry)"
    if not (FOOD_API_KEY.strip() and MODEL_ID.strip()):
        return "FOOD_API_KEY or MODEL_ID missing"
    if FOOD_PROVIDER == "local":
        return "FOOD_PROVIDER=local"
    if FOOD_PROVIDER not in ("auto", "hybrid", "api"):
        return f"FOOD_PROVIDER={FOOD_PROVIDER!r}"

    best = _local_best_confidence(local_foods)
    if local_foods and best >= CLARIFAI_SKIP_IF_LOCAL_CONF:
        return f"local confident enough (best={best:.2f} >= {CLARIFAI_SKIP_IF_LOCAL_CONF})"

    last = _last_clarifai_ts.get(user_id, 0.0)
    if now - last < CLARIFAI_MIN_INTERVAL_S:
        return f"rate limit ({now - last:.1f}s < {CLARIFAI_MIN_INTERVAL_S}s)"
    return None


def _should_call_clarifai(
    user_id: str,
    local_foods: dict[str, float],
    *,
    now: float,
) -> bool:
    return _clarifai_skip_reason(user_id, local_foods, now=now) is None


def reset_clarifai_for_new_session() -> None:
    """Call on app startup so a previous error does not block Clarifai for the whole run."""
    global _clarifai_disabled
    _clarifai_disabled = False


# Coalesce canvas uploads: only process the newest frame per user (avoids 10s+ UI lag on CPU).
_food_latest_frame: dict[str, Any] = {}
_food_drain_locks: dict[str, asyncio.Lock] = {}


async def _food_follow_up(
    main_food: str,
    food_list: dict[str, float],
    detection_sources: list[str],
    connections: dict,
    globalvars: dict,
    session_id,
) -> None:
    """Intolerance, nutrition, diary — after UI already received food name."""
    nutrition: dict = {}
    try:
        if globalvars.get("mainFood") != main_food:
            globalvars["mainFood"] = main_food
            await intol_processing(main_food, globalvars.get("intolerances", []), connections)
            if main_food != "unknown_food":
                nutrition = await nutrition_info(main_food, connections, session_id)
        await write_food_diary_and_allergen_log(
            globalvars=globalvars,
            food_name=main_food or "",
            confidence=food_list.get(main_food) if main_food else None,
            detected_foods=food_list,
            child_allergy_names=globalvars.get("intolerances", []),
            nutrition=nutrition or {},
            detection_sources=detection_sources or ["local"],
        )
    except Exception:
        logger.exception("Food follow-up (nutrition/diary) failed")


async def _process_food_frame(
    frame,
    user_id: str,
    connections: dict,
    globalvars: dict,
    session_id=None,
) -> None:
    frame_bytes = cv2.imencode(".jpg", frame)[1].tobytes()
    loop = asyncio.get_running_loop()
    food_exec = get_food_executor()

    local_foods, yolo_boxes = await loop.run_in_executor(
        food_exec, detect_food_local, frame
    )
    detection_sources: list[str] = []
    if local_foods:
        detection_sources.append("local")

    merged = dict(local_foods)
    clarifai_results: dict[str, float] = {}
    now = time.monotonic()
    clarifai_reason = _clarifai_skip_reason(user_id, local_foods, now=now)
    # Always try API when local YOLO found nothing (common for hand-held food).
    force_clarifai = not local_foods and FOOD_PROVIDER in ("auto", "hybrid", "api")
    if force_clarifai and clarifai_reason and clarifai_reason.startswith("rate limit"):
        clarifai_reason = None
    if clarifai_reason is None:
        _last_clarifai_ts[user_id] = now
        logger.info("[FOOD] Calling Clarifai (local_best=%.2f)...", _local_best_confidence(local_foods))
        clarifai_results = await loop.run_in_executor(food_exec, _call_clarifai, frame_bytes)
        if clarifai_results:
            detection_sources.append("clarifai")
            merged = merge_food_results(merged, clarifai_results)
        else:
            logger.info("[FOOD] Clarifai returned no whitelisted foods (min_conf=%.2f)", CLARIFAI_MIN_CONFIDENCE)
    else:
        logger.info("[FOOD] Clarifai skipped: %s", clarifai_reason)

    food_list = _filter_for_ui(merged)
    prev_ts = _last_food_emit_ts.get(user_id, 0.0)
    prev_main = _last_food_emit_main.get(user_id, "")

    if not food_list:
        if prev_main not in ("", "unknown_food") and (now - prev_ts) >= FOOD_CLEAR_DEBOUNCE_S:
            _last_food_emit_ts[user_id] = now
            _last_food_emit_main[user_id] = ""
            globalvars["mainFood"] = ""
            await _send_food_ws(
                user_id,
                connections,
                {"_state": 2, "food_list": {}, "food_main": "", "food_cleared": True, "boxes": []},
            )
            await broadcast_nutrition_clear(connections)
        return

    main_food = pick_main_food(food_list, clarifai=clarifai_results or None)
    if not main_food.strip():
        main_food = get_max_emotion(food_list)
    food_changed = main_food != prev_main
    if not food_changed and (now - prev_ts) < FOOD_MIN_INTERVAL_S:
        return

    _last_food_emit_ts[user_id] = now
    _last_food_emit_main[user_id] = main_food

    food_json = {
        "_state": 2,
        "food_list": food_list,
        "food_main": main_food,
        "boxes": yolo_boxes,
    }
    logger.info(
        "Food detected: main=%s list=%s sources=%s%s",
        main_food,
        food_list,
        "+".join(detection_sources) or "none",
        " (changed)" if food_changed else "",
    )

    await _send_food_ws(user_id, connections, food_json)

    try:
        await db.food_events().insert_one({
            "session_id": session_id,
            "timestamp": datetime.utcnow(),
            "detected_foods": food_list,
            "main_food": main_food,
            "intolerance_triggered": False,
            "sources": detection_sources,
        })
    except Exception:
        logger.exception("Failed to log food_event to MongoDB")

    asyncio.create_task(
        _food_follow_up(
            main_food,
            food_list,
            detection_sources,
            connections,
            globalvars,
            session_id,
        )
    )


async def send_frame_to_foodvisor(
    frame,
    user_id: str,
    connections: dict,
    globalvars: dict,
    session_id=None,
    food_near_person_xyxy: tuple[int, int, int, int] | None = None,
) -> None:
    """
    Full-frame food detection. ``food_near_person_xyxy`` is ignored (kept for API compat).
    Keeps only the latest canvas frame per user while inference is busy.
    """
    _ = food_near_person_xyxy
    uid = user_id or ""
    _food_latest_frame[uid] = frame

    if uid not in _food_drain_locks:
        _food_drain_locks[uid] = asyncio.Lock()

    lock = _food_drain_locks[uid]
    if lock.locked():
        return

    async with lock:
        while uid in _food_latest_frame:
            latest = _food_latest_frame.pop(uid)
            await _process_food_frame(latest, uid, connections, globalvars, session_id)
