"""
Food recognition & intolerance checking service.
Wraps Clarifai gRPC API calls.
"""

import logging
import cv2
from datetime import datetime

from clarifai_grpc.channel.clarifai_channel import ClarifaiChannel
from clarifai_grpc.grpc.api import resources_pb2, service_pb2, service_pb2_grpc
from clarifai_grpc.grpc.api.status import status_code_pb2

import db
from config import FOOD_API_KEY, MODEL_ID
from services.emotion import get_max_emotion
from services.nutrition import nutrition_info

logger = logging.getLogger(__name__)

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
    """Send a video frame to Clarifai, broadcast food results, log to MongoDB."""
    current_time = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    frame_bytes  = cv2.imencode('.jpg', frame)[1].tobytes()

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

    if response.status.code != status_code_pb2.SUCCESS:
        logger.warning("Clarifai call failed: %s", response.status.description)
        return

    food_list: dict[str, float] = {}
    for concept in response.outputs[0].data.concepts:
        if concept.value > 0.75:
            food_list[concept.name.lower()] = round(concept.value, 2)

    main_food = get_max_emotion(food_list)   # reuses "max value" helper
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

    # Intolerance + nutrition only when main food changes
    if globalvars.get("mainFood") != main_food:
        globalvars["mainFood"] = main_food
        await intol_processing(main_food, globalvars.get("intolerances", []), connections)
        await nutrition_info(main_food, connections, session_id)
