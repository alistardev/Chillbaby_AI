"""
Food recognition & intolerance checking.

Pipeline (full camera frame — child and food anywhere in view):
  1. Local YOLO (food_detector.pt), optional COCO yolov8m when primary misses
  2. Clarifai only as fallback when local is empty/weak (saves API credits)
"""

from __future__ import annotations

import logging
import asyncio
import concurrent.futures
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
    CLARIFAI_MISS_CACHE_TTL_S,
    CLARIFAI_EMPTY_INTERVAL_S,
    CLARIFAI_EMPTY_MISS_CACHE_TTL_S,
    CLARIFAI_SKIP_IF_LOCAL_CONF,
    CLARIFAI_WHEN_LOCAL_EMPTY,
    CLARIFAI_USER_ID,
    FOOD_API_KEY,
    FOOD_API_KEY_2,
    FOOD_PROVIDER,
    FOOD_MIN_CONFIDENCE,
    FOOD_MIN_INTERVAL_S,
    FOOD_CLEAR_DEBOUNCE_S,
    FOOD_SESSION_BOOT_DELAY_S,
    LOCAL_FOOD_WEAK_MIN,
    LOCAL_LABEL_HOLD_S,
    ALLERGEN_ALERT_COOLDOWN_S,
    MODEL_ID,
    MODEL_VERSION_ID,
)
from services.local_food_detector import detect_food_local, friendly_food_label, get_food_executor
from services.allergen_lookup import check_food_allergens
from services.domain_writes import write_food_diary_and_allergen_log
from services.emotion import get_max_emotion
from services.nutrition import broadcast_nutrition_clear, nutrition_info

logger = logging.getLogger(__name__)

FOOD_STATUS_SEARCHING = "searching"
FOOD_STATUS_NONE = "none"
FOOD_MARKER_SEARCHING = "__searching__"
FOOD_DISPLAY_SEARCHING = "Identifying… checking cloud API"
FOOD_DISPLAY_NONE = "No food detected"


def _food_names_match(a: str, b: str) -> bool:
    al = (friendly_food_label(a) or a or "").lower().strip()
    bl = (friendly_food_label(b) or b or "").lower().strip()
    if not al or not bl:
        return False
    return al == bl or al in bl or bl in al


_last_food_emit_ts: dict[str, float] = {}
_last_food_emit_main: dict[str, str] = {}
_last_clarifai_ts: dict[str, float] = {}
_last_allergen_alert: dict[str, float] = {}  # key: "uid:food", value: monotonic ts
_last_allergen_ui_key: dict[str, str] = {}  # last (food, matched) fingerprint sent to UI
# Negative cache: local fingerprint → Clarifai already returned nothing (saves API credits).
_clarifai_miss_cache: dict[str, tuple[str, float]] = {}

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
    "broccoli", "carrot", "tomato", "cucumber", "cucumbers", "spinach", "lettuce",
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

# COCO yolov8m often labels hand-held items as sandwich/cake — downrank only those when picking main food.
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
    Choose display food — Clarifai overrides local only when local score is below skip threshold.
    """
    if not merged and not clarifai:
        return ""

    if clarifai and merged:
        cf_best = max(clarifai, key=clarifai.get)
        cf_score = float(clarifai[cf_best])
        local_best = max(merged, key=lambda k: float(merged[k]))
        local_score = float(merged[local_best])
        if cf_score >= CLARIFAI_MIN_CONFIDENCE and local_score < CLARIFAI_SKIP_IF_LOCAL_CONF:
            return cf_best

    if not merged:
        if clarifai:
            cf_best = max(clarifai, key=clarifai.get)
            if float(clarifai[cf_best]) >= CLARIFAI_MIN_CONFIDENCE:
                return cf_best
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
            and float(merged.get(main, 0)) < CLARIFAI_SKIP_IF_LOCAL_CONF
        ):
            return cf_best

    for name, conf in ranked:
        if name not in _GENERIC_COCO_FOODS and float(conf) >= FOOD_MIN_CONFIDENCE:
            return name

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
        canonical = _normalize_clarifai_food(name)
        if canonical:
            raw[canonical] = max(raw.get(canonical, 0.0), round(conf, 2))
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


def _normalize_clarifai_food(name: str) -> str | None:
    """Map Clarifai concept text to a whitelist food (substring match for 'green grape', 'bread loaf')."""
    n = (name or "").lower().strip().replace("_", " ")
    if not n:
        return None
    if n in _FOOD_WHITELIST:
        return n
    if "grapefruit" in n:
        return "grapefruit"
    if "grape" in n or "raisin" in n:
        return "grapes"
    if "strawberr" in n:
        return "strawberry"
    if "cucumber" in n or "pickle" in n:
        return "cucumber"
    if any(k in n for k in ("bread", "baguette", "loaf", "bagel", "bun")):
        return "bread"
    if "banana" in n:
        return "banana"
    best = ""
    for word in sorted(_FOOD_WHITELIST, key=len, reverse=True):
        if word in n or n in word:
            if len(word) > len(best):
                best = word
    return best or None


_clarifai_reject_log_ts: float = 0.0


def _concepts_json_to_food(concepts: list) -> dict[str, float]:
    raw: dict[str, float] = {}
    rejected: list[tuple[str, float]] = []
    for concept in concepts:
        if isinstance(concept, dict):
            conf = float(concept.get("value", 0))
            name = str(concept.get("name", "")).lower().strip()
        else:
            conf = float(concept.value)
            name = str(concept.name).lower().strip()
        if conf < CLARIFAI_MIN_CONFIDENCE:
            rejected.append((name, conf))
            continue
        canonical = _normalize_clarifai_food(name)
        if canonical:
            raw[canonical] = max(raw.get(canonical, 0.0), round(conf, 2))
        else:
            rejected.append((name, conf))

    if not raw and rejected:
        global _clarifai_reject_log_ts
        now = time.monotonic()
        if now - _clarifai_reject_log_ts >= 30.0:
            _clarifai_reject_log_ts = now
            top = sorted(rejected, key=lambda x: -x[1])[:8]
            logger.info(
                "[FOOD] Clarifai concepts below whitelist/min_conf (top): %s",
                ", ".join(f"{n}={c:.2f}" for n, c in top),
            )
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
        if e.code in (402, 403) or "insufficient credit" in detail.lower():
            global _clarifai_disabled
            _clarifai_disabled = True
            logger.warning("Clarifai disabled for this session (billing/permission). Using local YOLO only.")
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
    hay = (s or "").lower()
    return any(str(sub).lower() in hay for sub in substrings if sub)


def _match_allergens_for_food(
    main_food: str,
    detected_foods: dict[str, float],
    intolerances: list[str],
) -> list[str]:
    """Fast sync match for UI — mirrors domain_writes map + substring fallback."""
    if not main_food or not intolerances:
        return []
    matched = check_food_allergens(main_food, intolerances)
    if matched:
        return matched
    hay = " ".join([main_food] + list(detected_foods.keys())).lower()
    return [name for name in intolerances if str(name).lower() in hay]


async def _reset_allergen_ui(
    user_id: str,
    connections: dict,
    globalvars: dict,
) -> None:
    """Force-clear allergen overlay when food leaves the frame or scene is re-scanning."""
    _last_allergen_ui_key.pop(user_id, None)
    await _sync_allergen_ui(user_id, "", {}, connections, globalvars)


async def _sync_allergen_ui(
    user_id: str,
    main_food: str,
    detected_foods: dict[str, float],
    connections: dict,
    globalvars: dict,
) -> None:
    """Push _state:8 immediately when food label or allergen match changes (not throttled with food label)."""
    if not connections:
        return
    intolerances = globalvars.get("intolerances") or []
    food_key = (main_food or "").strip().lower()

    if not intolerances or not food_key or food_key == "unknown_food":
        ui_key = "clear"
        matched: list[str] = []
    else:
        matched = _match_allergens_for_food(main_food, detected_foods, intolerances)
        ui_key = f"{food_key}|{'+'.join(sorted(m.lower() for m in matched))}"

    if _last_allergen_ui_key.get(user_id) == ui_key:
        return

    if matched:
        cooldown_key = f"{user_id}:{food_key}"
        now_mono = time.monotonic()
        last_sent = _last_allergen_alert.get(cooldown_key, 0.0)
        if now_mono - last_sent < ALLERGEN_ALERT_COOLDOWN_S:
            return
        _last_allergen_alert[cooldown_key] = now_mono
        _last_allergen_ui_key[user_id] = ui_key
        payload = {
            "_state": 8,
            "food": main_food,
            "allergens": matched,
            "severity": "high" if len(matched) > 1 else "medium",
            "alert_triggered": True,
        }
    else:
        _last_allergen_ui_key[user_id] = ui_key
        payload = {
            "_state": 8,
            "food": main_food or "",
            "allergens": [],
            "alert_triggered": False,
        }

    await _send_food_ws(user_id, connections, payload)


async def intol_processing(main_food: str, intolerances: list, connections: dict) -> None:
    logger.info("Intolerance check: food=%s intolerances=%s", main_food, intolerances)
    answer = "yes" if check_substrings(main_food, intolerances) else "no"
    payload = {"_state": 4, "result": answer}
    for ws in connections.values():
        await ws.send_json(payload)


async def _send_food_ws(user_id: str, connections: dict, payload: dict) -> None:
    if not connections:
        logger.warning(
            "Food emit: no WebSocket clients (token=%s state=%s)",
            (user_id or "")[:16],
            payload.get("_state"),
        )
        return
    dead: list[str] = []
    for uid, ws in list(connections.items()):
        try:
            await ws.send_json(payload)
        except Exception:
            logger.exception("Food emit failed for token=%s", uid[:16])
            dead.append(uid)
    for uid in dead:
        connections.pop(uid, None)


def _filter_for_ui(food_list: dict[str, float], *, hold_label: str = "") -> dict[str, float]:
    out: dict[str, float] = {}
    hold = (hold_label or "").strip().lower()
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
        elif hold and s >= LOCAL_FOOD_WEAK_MIN and _food_names_match(name, hold_label):
            out[name] = s
    return out


def _local_top_label(local_foods: dict[str, float]) -> str:
    if not local_foods:
        return ""
    return max(local_foods, key=lambda k: float(local_foods[k]))


def _local_is_trusted(local_foods: dict[str, float]) -> bool:
    if not local_foods:
        return False
    return _local_best_score(local_foods) >= CLARIFAI_SKIP_IF_LOCAL_CONF


def _filter_local_for_early_emit(local_foods: dict[str, float], user_id: str = "") -> dict[str, float]:
    hold = _last_food_emit_main.get(user_id, "") if user_id else ""
    return _filter_for_ui(dict(local_foods), hold_label=hold)


async def _emit_local_fallback(
    local_foods: dict[str, float],
    *,
    user_id: str,
    connections: dict,
    globalvars: dict,
    session_id,
    yolo_boxes: list,
    detection_sources: list[str],
) -> bool:
    """When Clarifai misses, still show a good local YOLO label (banana, carrot, …)."""
    fallback = _filter_for_ui(dict(local_foods), hold_label=_last_food_emit_main.get(user_id, ""))
    if not fallback:
        return False
    await _emit_food_if_changed(
        user_id=user_id,
        connections=connections,
        globalvars=globalvars,
        session_id=session_id,
        food_list=fallback,
        yolo_boxes=yolo_boxes,
        detection_sources=detection_sources,
    )
    return True


def _local_best_score(local_foods: dict[str, float]) -> float:
    """Best raw score from local YOLO + COCO merge (any label)."""
    if not local_foods:
        return 0.0
    return max(float(v) for v in local_foods.values())


def _local_best_confidence(local_foods: dict[str, float]) -> float:
    ui = _filter_for_ui(local_foods)
    if not ui:
        return 0.0
    return max(float(v) for v in ui.values())


def _local_clarifai_fingerprint(local_foods: dict[str, float]) -> str:
    """Stable key for the current local YOLO view — used to avoid repeat Clarifai calls."""
    if not local_foods:
        return "empty"
    items: list[tuple[str, float]] = []
    for name, conf in local_foods.items():
        try:
            c = float(conf)
        except Exception:
            continue
        label = friendly_food_label(name) or str(name).lower().strip()
        if label:
            items.append((label, c))
    if not items:
        return "empty"
    items.sort(key=lambda x: (-x[1], x[0]))
    return "|".join(f"{n}:{c:.1f}" for n, c in items[:4])


def _record_clarifai_miss(user_id: str, fingerprint: str, *, now: float) -> None:
    _clarifai_miss_cache[user_id] = (fingerprint, now)
    logger.info(
        "[FOOD] Clarifai miss cached for %ds (fingerprint=%s)",
        int(CLARIFAI_MISS_CACHE_TTL_S),
        fingerprint,
    )


def _clarifai_miss_skip_reason(user_id: str, fingerprint: str, *, now: float) -> str | None:
    entry = _clarifai_miss_cache.get(user_id)
    if not entry:
        return None
    cached_fp, miss_at = entry
    if cached_fp != fingerprint:
        return None
    age = now - miss_at
    ttl = CLARIFAI_EMPTY_MISS_CACHE_TTL_S if cached_fp == "empty" else CLARIFAI_MISS_CACHE_TTL_S
    if age >= ttl:
        return None
    return f"Clarifai already failed for this view ({cached_fp}, {age:.0f}s ago)"


def _person_in_food_frame(frame, globalvars: dict) -> bool:
    """Re-detect person on each food canvas frame (don't use stale WebRTC cache)."""
    if frame is None:
        if globalvars.get("processing"):
            return globalvars.get("personPresent") is not False
        return bool(globalvars.get("personPresent"))
    try:
        from services.child_detector import detect

        present, conf, _ = detect(frame)
        globalvars["personPresent"] = present
        if not present:
            logger.debug("Food canvas: no person box (conf=%.2f)", conf)
        return present
    except Exception:
        logger.debug("Person check on food frame failed", exc_info=True)
        return True


def _clarifai_skip_reason(
    user_id: str,
    local_foods: dict[str, float],
    *,
    now: float,
    globalvars: dict | None = None,
    frame=None,
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

    # Local + COCO empty: Clarifai for hand-held foods YOLO misses (cucumber, bread, grapes, …).
    if not local_foods:
        prev = _last_food_emit_main.get(user_id, "")
        if prev and prev not in ("", FOOD_MARKER_SEARCHING, "unknown_food", "mixed_food"):
            age = now - _last_food_emit_ts.get(user_id, 0.0)
            if age < LOCAL_LABEL_HOLD_S:
                return f"recent local label ({prev}, {age:.1f}s ago)"
        mode = CLARIFAI_WHEN_LOCAL_EMPTY
        if mode in ("0", "false", "no", "never"):
            return "local + COCO found no food"
        if mode in ("person", "child"):
            meal_active = bool(globalvars and globalvars.get("processing"))
            has_person = True
            if frame is not None:
                has_person = _person_in_food_frame(frame, globalvars or {})
            elif globalvars is not None and globalvars.get("personPresent") is False:
                has_person = False
            if not has_person and not meal_active:
                return "local + COCO empty and no person in frame"
            if not has_person and meal_active:
                logger.debug(
                    "[FOOD] No person box on food frame but meal active — Clarifai probe allowed"
                )
        miss = _clarifai_miss_skip_reason(user_id, "empty", now=now)
        if miss:
            return miss
        last = _last_clarifai_ts.get(user_id, 0.0)
        if now - last < CLARIFAI_EMPTY_INTERVAL_S:
            return f"empty-local rate limit ({now - last:.1f}s < {CLARIFAI_EMPTY_INTERVAL_S}s)"
        return None

    best = _local_best_score(local_foods)
    if local_foods and best >= LOCAL_FOOD_WEAK_MIN:
        return f"local YOLO hint (best={best:.2f} >= {LOCAL_FOOD_WEAK_MIN})"
    if not CLARIFAI_MERGE_EVERY_FRAME and local_foods and best >= FOOD_MIN_CONFIDENCE:
        return f"local has food (best={best:.2f})"
    if best >= CLARIFAI_SKIP_IF_LOCAL_CONF:
        return f"local confident enough (best={best:.2f} >= {CLARIFAI_SKIP_IF_LOCAL_CONF})"

    fingerprint = _local_clarifai_fingerprint(local_foods)
    miss = _clarifai_miss_skip_reason(user_id, fingerprint, now=now)
    if miss:
        return miss

    last = _last_clarifai_ts.get(user_id, 0.0)
    if now - last < CLARIFAI_MIN_INTERVAL_S:
        return f"rate limit ({now - last:.1f}s < {CLARIFAI_MIN_INTERVAL_S}s)"
    return None


def _should_call_clarifai(
    user_id: str,
    local_foods: dict[str, float],
    *,
    now: float,
    globalvars: dict | None = None,
    frame=None,
) -> bool:
    return _clarifai_skip_reason(
        user_id, local_foods, now=now, globalvars=globalvars, frame=frame
    ) is None


def _will_call_clarifai(
    user_id: str,
    local_foods: dict[str, float],
    *,
    now: float,
    globalvars: dict | None = None,
    frame=None,
) -> bool:
    if FOOD_PROVIDER not in ("auto", "hybrid", "api"):
        return False
    return _clarifai_skip_reason(
        user_id, local_foods, now=now, globalvars=globalvars, frame=frame
    ) is None


async def _emit_food_status(
    *,
    user_id: str,
    connections: dict,
    globalvars: dict,
    status: str,
    display: str,
    clear_nutrition: bool = False,
) -> None:
    """Push interim UI (searching / no food) so stale labels are not left on screen."""
    prev = _last_food_emit_main.get(user_id, "")
    if status == FOOD_STATUS_SEARCHING and prev == FOOD_MARKER_SEARCHING:
        return
    if status == FOOD_STATUS_NONE and prev == "" and not globalvars.get("mainFood"):
        return

    had_real_food = prev not in ("", FOOD_MARKER_SEARCHING, "unknown_food", "mixed_food")
    if status == FOOD_STATUS_NONE or (status == FOOD_STATUS_SEARCHING and had_real_food):
        await _reset_allergen_ui(user_id, connections, globalvars)

    now = time.monotonic()
    _last_food_emit_ts[user_id] = now
    if status == FOOD_STATUS_SEARCHING:
        _last_food_emit_main[user_id] = FOOD_MARKER_SEARCHING
    else:
        _last_food_emit_main[user_id] = ""
        globalvars["mainFood"] = ""

    await _send_food_ws(
        user_id,
        connections,
        {
            "_state": 2,
            "food_status": status,
            "food_display": display,
            "food_main": "",
            "food_list": {},
            "boxes": [],
            "food_cleared": status == FOOD_STATUS_NONE,
        },
    )
    if clear_nutrition:
        await broadcast_nutrition_clear(connections)


def reset_clarifai_for_new_session() -> None:
    """Call on app startup so a previous error does not block Clarifai for the whole run."""
    global _clarifai_disabled
    _clarifai_disabled = False
    _clarifai_miss_cache.clear()


def clear_clarifai_miss_cache(user_id: str = "") -> None:
    """Clear negative cache when a new meal session starts (allows one retry per scene)."""
    if user_id:
        _clarifai_miss_cache.pop(user_id, None)
    else:
        _clarifai_miss_cache.clear()


# Coalesce canvas uploads: only process the newest frame per user (avoids 10s+ UI lag on CPU).
_food_latest_frame: dict[str, Any] = {}
_food_drain_locks: dict[str, asyncio.Lock] = {}


def is_food_pipeline_busy(user_id: str | None = None) -> bool:
    """True only while food YOLO is actively running (not merely queued)."""
    if user_id:
        uid = user_id or ""
        lock = _food_drain_locks.get(uid)
        return bool(lock and lock.locked())
    return any(lock.locked() for lock in _food_drain_locks.values())
# Clarifai HTTP runs off the single YOLO worker so inference is not blocked behind API latency.
_clarifai_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="food-clarifai"
)


async def _food_follow_up(
    main_food: str,
    food_list: dict[str, float],
    detection_sources: list[str],
    connections: dict,
    globalvars: dict,
    session_id,
    user_id: str = "",
) -> None:
    """Intolerance, nutrition, diary — after UI already received food name."""
    nutrition: dict = {}
    try:
        if globalvars.get("mainFood") != main_food:
            globalvars["mainFood"] = main_food
            if main_food != "unknown_food":
                nutrition = await nutrition_info(main_food, connections, session_id)
            if globalvars.get("intolerances") and main_food != "unknown_food":
                asyncio.create_task(
                    intol_processing(main_food, globalvars.get("intolerances", []), connections)
                )
            matched_allergens = await write_food_diary_and_allergen_log(
                globalvars=globalvars,
                food_name=main_food or "",
                confidence=food_list.get(main_food) if main_food else None,
                detected_foods=food_list,
                child_allergy_names=globalvars.get("intolerances", []),
                nutrition=nutrition or {},
                detection_sources=detection_sources or ["local"],
            )
            _ = matched_allergens  # UI alert is pushed immediately via _sync_allergen_ui
    except Exception:
        logger.exception("Food follow-up (nutrition/diary) failed")


async def _food_post_emit(
    main_food: str,
    food_list: dict[str, float],
    detection_sources: list[str],
    connections: dict,
    globalvars: dict,
    session_id,
    user_id: str = "",
) -> None:
    """Mongo log + nutrition/diary — must not block the food label WebSocket."""
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
    await _food_follow_up(
        main_food,
        food_list,
        detection_sources,
        connections,
        globalvars,
        session_id,
        user_id=user_id,
    )


async def _emit_food_if_changed(
    *,
    user_id: str,
    connections: dict,
    globalvars: dict,
    session_id,
    food_list: dict[str, float],
    yolo_boxes: list,
    detection_sources: list[str],
    clarifai_results: dict[str, float] | None = None,
) -> bool:
    """Push _state:2 when label changed or throttle window elapsed. Returns True if emitted."""
    now = time.monotonic()
    prev_ts = _last_food_emit_ts.get(user_id, 0.0)
    prev_main = _last_food_emit_main.get(user_id, "")

    if not food_list:
        if prev_main not in ("", "unknown_food") and (now - prev_ts) >= FOOD_CLEAR_DEBOUNCE_S:
            _last_food_emit_ts[user_id] = now
            _last_food_emit_main[user_id] = ""
            globalvars["mainFood"] = ""
            await _reset_allergen_ui(user_id, connections, globalvars)
            await _send_food_ws(
                user_id,
                connections,
                {"_state": 2, "food_list": {}, "food_main": "", "food_cleared": True, "boxes": []},
            )
            await broadcast_nutrition_clear(connections)
        return False

    main_food = pick_main_food(food_list, clarifai=clarifai_results or None)
    if not main_food.strip():
        main_food = get_max_emotion(food_list)
    food_changed = main_food != prev_main
    if food_changed:
        await _sync_allergen_ui(
            user_id, main_food, food_list, connections, globalvars
        )
    if not food_changed and (now - prev_ts) < FOOD_MIN_INTERVAL_S:
        return False

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
    asyncio.create_task(
        _food_post_emit(
            main_food,
            food_list,
            detection_sources,
            connections,
            globalvars,
            session_id,
            user_id=user_id,
        )
    )
    return True


async def _process_food_frame(
    frame,
    user_id: str,
    connections: dict,
    globalvars: dict,
    session_id=None,
) -> None:
    uid = user_id or ""

    def _superseded() -> bool:
        return uid in _food_latest_frame

    if _superseded():
        return

    t0 = time.monotonic()
    frame_bytes = cv2.imencode(".jpg", frame)[1].tobytes()
    loop = asyncio.get_running_loop()
    food_exec = get_food_executor()

    local_foods, yolo_boxes = await loop.run_in_executor(
        food_exec, detect_food_local, frame
    )
    # Do not skip emit after YOLO when a newer canvas frame arrived — that dropped
    # food-change updates while inference was still running (~0.8s capture vs ~1s YOLO).

    local_ms = int((time.monotonic() - t0) * 1000)
    if local_ms > 1500:
        logger.warning(
            "Local food YOLO slow: %dms — try LOCAL_FOOD_PREDICT_IMGSZ=384 "
            "FOOD_CANVAS_MAX_DIM=640 on CPU servers",
            local_ms,
        )

    detection_sources: list[str] = []
    if local_foods:
        detection_sources.append("local")

    local_ui = _filter_local_for_early_emit(dict(local_foods), user_id)
    now = time.monotonic()

    if local_ui:
        preview_main = pick_main_food(local_ui)
        if not preview_main.strip():
            preview_main = get_max_emotion(local_ui)
        stale = _superseded()
        would_change = preview_main != _last_food_emit_main.get(user_id, "")
        if stale and not would_change:
            return
        await _emit_food_if_changed(
            user_id=user_id,
            connections=connections,
            globalvars=globalvars,
            session_id=session_id,
            food_list=local_ui,
            yolo_boxes=yolo_boxes,
            detection_sources=list(detection_sources),
        )
    else:
        prev_main = _last_food_emit_main.get(user_id, "")
        had_food_label = prev_main not in ("", FOOD_MARKER_SEARCHING)
        if _will_call_clarifai(user_id, local_foods, now=now, globalvars=globalvars, frame=frame):
            await _emit_food_status(
                user_id=user_id,
                connections=connections,
                globalvars=globalvars,
                status=FOOD_STATUS_SEARCHING,
                display=FOOD_DISPLAY_SEARCHING,
            )
        elif had_food_label:
            await _emit_food_status(
                user_id=user_id,
                connections=connections,
                globalvars=globalvars,
                status=FOOD_STATUS_NONE,
                display=FOOD_DISPLAY_NONE,
                clear_nutrition=True,
            )

    clarifai_reason = _clarifai_skip_reason(
        user_id, local_foods, now=now, globalvars=globalvars, frame=frame
    )
    if clarifai_reason is not None:
        if local_ui:
            logger.debug("[FOOD] Clarifai skipped after fast local emit: %s", clarifai_reason)
        else:
            logger.info("[FOOD] Clarifai skipped: %s", clarifai_reason)
            if _last_food_emit_main.get(user_id) == FOOD_MARKER_SEARCHING:
                if not await _emit_local_fallback(
                    local_foods,
                    user_id=user_id,
                    connections=connections,
                    globalvars=globalvars,
                    session_id=session_id,
                    yolo_boxes=yolo_boxes,
                    detection_sources=list(detection_sources),
                ):
                    await _emit_food_status(
                        user_id=user_id,
                        connections=connections,
                        globalvars=globalvars,
                        status=FOOD_STATUS_NONE,
                        display=FOOD_DISPLAY_NONE,
                        clear_nutrition=True,
                    )
        return

    _last_clarifai_ts[user_id] = now
    clarifai_fp = _local_clarifai_fingerprint(local_foods)
    logger.info("[FOOD] Calling Clarifai (local_best=%.2f fp=%s)...", _local_best_score(local_foods), clarifai_fp)
    clarifai_results = await loop.run_in_executor(
        _clarifai_executor, _call_clarifai, frame_bytes
    )
    if clarifai_results:
        detection_sources.append("clarifai")
        _clarifai_miss_cache.pop(user_id, None)
    else:
        logger.info("[FOOD] Clarifai returned no whitelisted foods (min_conf=%.2f)", CLARIFAI_MIN_CONFIDENCE)
        _record_clarifai_miss(user_id, clarifai_fp, now=time.monotonic())
        if not await _emit_local_fallback(
            local_foods,
            user_id=user_id,
            connections=connections,
            globalvars=globalvars,
            session_id=session_id,
            yolo_boxes=yolo_boxes,
            detection_sources=list(detection_sources),
        ):
            await _emit_food_status(
                user_id=user_id,
                connections=connections,
                globalvars=globalvars,
                status=FOOD_STATUS_NONE,
                display=FOOD_DISPLAY_NONE,
                clear_nutrition=True,
            )
        return

    merged = merge_food_results(dict(local_foods), clarifai_results)
    merged_ui = _filter_for_ui(merged)
    if not merged_ui:
        _record_clarifai_miss(user_id, clarifai_fp, now=time.monotonic())
        if not await _emit_local_fallback(
            local_foods,
            user_id=user_id,
            connections=connections,
            globalvars=globalvars,
            session_id=session_id,
            yolo_boxes=yolo_boxes,
            detection_sources=list(detection_sources),
        ):
            await _emit_food_status(
                user_id=user_id,
                connections=connections,
                globalvars=globalvars,
                status=FOOD_STATUS_NONE,
                display=FOOD_DISPLAY_NONE,
                clear_nutrition=True,
            )
        return
    await _emit_food_if_changed(
        user_id=user_id,
        connections=connections,
        globalvars=globalvars,
        session_id=session_id,
        food_list=merged_ui,
        yolo_boxes=yolo_boxes,
        detection_sources=detection_sources,
        clarifai_results=clarifai_results,
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

    if FOOD_SESSION_BOOT_DELAY_S > 0:
        started = globalvars.get("processing_started_mono")
        if started is not None:
            age = time.monotonic() - float(started)
            if age < FOOD_SESSION_BOOT_DELAY_S:
                prev = _last_food_emit_main.get(uid, "")
                if prev in ("", FOOD_MARKER_SEARCHING):
                    return

    _food_latest_frame[uid] = frame

    if uid not in _food_drain_locks:
        _food_drain_locks[uid] = asyncio.Lock()

    lock = _food_drain_locks[uid]
    if lock.locked():
        return

    async with lock:
        while uid in _food_latest_frame:
            latest = _food_latest_frame.pop(uid)
            while uid in _food_latest_frame:
                latest = _food_latest_frame.pop(uid)
            await _process_food_frame(latest, uid, connections, globalvars, session_id)
