"""
Azure OpenAI nutrition info service.
Updated for openai >= 1.0 (AzureOpenAI client).
"""

import logging
import re
from openai import AzureOpenAI

from config import OPENAI_API_KEY, OPENAI_API_BASE, OPENAI_API_VERSION, OPENAI_ENGINE

logger = logging.getLogger(__name__)

# Single shared AzureOpenAI client (instantiated once at import time)
_client = AzureOpenAI(
    api_key=OPENAI_API_KEY,
    api_version=OPENAI_API_VERSION,
    azure_endpoint=OPENAI_API_BASE,
)


async def nutrition_info(food: str, connections: dict, session_id=None) -> None:
    """
    Call Azure OpenAI to get nutritional info for a food item and
    broadcast the result to all connected WebSocket clients.
    """
    logger.info("Fetching nutrition info for: %s", food)

    messages = [
        {
            "role": "system",
            "content": (
                "You are an AI assistant that helps people find answers. "
                "Please reply with the following style: info = Your_Answer"
            ),
        },
        {
            "role": "user",
            "content": (
                f"What is the nutritional info of {food}? "
                "Please display only nutrition name and value."
            ),
        },
    ]

    try:
        response = _client.chat.completions.create(
            model=OPENAI_ENGINE,
            messages=messages,
            temperature=0.8,
            max_tokens=400,
            top_p=0.95,
            frequency_penalty=0,
            presence_penalty=0,
        )
        answer = response.choices[0].message.content
    except Exception:
        logger.exception("OpenAI nutrition call failed for food=%s", food)
        return

    matches    = re.findall(r'(.+): (.+)', answer)
    answer_str = "".join(f"{m[0]}: {m[1]}" for m in matches)

    payload = {"_state": 5, "result": answer_str}
    for ws in connections.values():
        await ws.send_json(payload)

    logger.debug("Nutrition info sent: %s", answer_str[:120])
