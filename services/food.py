"""
Food recognition & intolerance checking service.
Wraps Clarifai gRPC API calls.
"""

import logging
import cv2
import time
from datetime import datetime

from clarifai_grpc.channel.clarifai_channel import ClarifaiChannel
from clarifai_grpc.grpc.api import resources_pb2, service_pb2, service_pb2_grpc
from clarifai_grpc.grpc.api.status import status_code_pb2

import db
from config import (
    FOOD_API_KEY,
    MODEL_ID,
    FOOD_PROVIDER,
    FOOD_MIN_CONFIDENCE,
    FOOD_MIN_INTERVAL_S,
)
from services.local_food_detector import detect_food_local
from services.domain_writes import write_food_diary_and_allergen_log
from services.emotion import get_max_emotion
from services.nutrition import nutrition_info

logger = logging.getLogger(__name__)
_last_food_emit_ts: dict[str, float] = {}
_last_food_emit_main: dict[str, str] = {}

# ── Clarifai client (initialised once) ───────────────────────────────────────
_metadata = (('authorization', 'Key ' + FOOD_API_KEY),)
_channel  = ClarifaiChannel.get_grpc_channel()
_stub     = service_pb2_grpc.V2Stub(_channel)


def check_substrings(s: str, substrings: list) -> bool:
    """Return True if any substring from the list appears in s."""
    return any(sub in s for sub in substrings)


async def intol_processing(main_food: str, intolerances: list, connections: dict) -> None:
    """Check detected food against the user's intolerance list and broadcast result."""
    logger.info("Intolerance check: food=%s intolerances=%s", main_food, intolerances)
    answer = "yes" if check_substrings(main_food, intolerances) else "no"
    payload = {"_state": 4, "result": answer}
    for ws in connections.values():
        await ws.send_json(payload)


async def send_frame_to_foodvisor(
    frame,
    user_id: str,
    connections: dict,
    globalvars: dict,
    session_id=None,
) -> None:
    """
    Local-first food detection.

    - Always attempts local model first.
    - If API credentials exist, can merge/augment with Clarifai.
    - If API is unavailable, runs fully local.
    """
    frame_bytes  = cv2.imencode('.jpg', frame)[1].tobytes()
    detection_sources: list[str] = []
    food_list: dict[str, float] = {}

    # 1) Local-first
    local_foods = detect_food_local(frame)
    if local_foods:
        food_list.update(local_foods)
        detection_sources.append("local")

    # 2) Optional API augmentation/fallback
    api_enabled = bool(FOOD_API_KEY.strip() and MODEL_ID.strip())
    use_api = FOOD_PROVIDER in ("auto", "hybrid", "api") and api_enabled
    if use_api:
        try:
            request = service_pb2.PostModelOutputsRequest(
                model_id=MODEL_ID,
                inputs=[
                    resources_pb2.Input(
                        data=resources_pb2.Data(
                            image=resources_pb2.Image(base64=frame_bytes)
                        )
                    )
                ],
            )

            response = _stub.PostModelOutputs(request, metadata=_metadata)
            if response.status.code == status_code_pb2.SUCCESS:
                detection_sources.append("clarifai")
                for concept in response.outputs[0].data.concepts:
                    conf = round(float(concept.value), 2)
                    if conf < 0.40:
                        continue
                    name = concept.name.lower().strip()
                    food_list[name] = max(food_list.get(name, 0.0), conf)
            else:
                logger.warning("Clarifai call failed: %s", response.status.description)
        except Exception:
            logger.exception("Clarifai call errored; continuing with local results.")

    filtered_foods: dict[str, float] = {}
    for name, score in food_list.items():
        try:
            s = float(score)
        except Exception:
            continue
        # Keep unknown_food slightly more permissive so local-only generic cls
        # still produces a usable signal instead of dropping all frames.
        min_conf = FOOD_MIN_CONFIDENCE
        if name == "unknown_food":
            min_conf = max(0.08, FOOD_MIN_CONFIDENCE * 0.66)
        if s >= min_conf:
            filtered_foods[name] = s
    food_list = filtered_foods

    if not food_list:
        # No detection from local or API; nothing to emit/log this frame.
        return

    main_food = get_max_emotion(food_list)   # reuses "max value" helper
    now = time.monotonic()
    prev_ts = _last_food_emit_ts.get(user_id, 0.0)
    prev_main = _last_food_emit_main.get(user_id, "")
    if prev_main == main_food and (now - prev_ts) < FOOD_MIN_INTERVAL_S:
        return
    _last_food_emit_ts[user_id] = now
    _last_food_emit_main[user_id] = main_food

    food_json = {
        "_state":     2,
        "food_list":  food_list,
        "food_main":  main_food,
    }

    logger.info("Food detected: main=%s list=%s", main_food, food_list)

    # Broadcast to all connected WebSocket clients
    for ws in connections.values():
        await ws.send_json(food_json)

    # Persist to MongoDB
    try:
        doc = {
            "session_id":            session_id,
            "timestamp":             datetime.utcnow(),
            "detected_foods":        food_list,
            "main_food":             main_food,
            "intolerance_triggered": False,  # updated below if needed
        }
        await db.food_events().insert_one(doc)
    except Exception:
        logger.exception("Failed to log food_event to MongoDB")

    nutrition = {}
    # Intolerance + nutrition only when main food changes
    if globalvars.get("mainFood") != main_food:
        globalvars["mainFood"] = main_food
        await intol_processing(main_food, globalvars.get("intolerances", []), connections)
        if main_food != "unknown_food":
            nutrition = await nutrition_info(main_food, connections, session_id)

    # Additive write to new logical collections (non-breaking path).
    try:
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
        logger.exception("Failed additive food/allergen writes")
