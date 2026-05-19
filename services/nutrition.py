"""
Nutrition for the UI: Azure OpenAI and/or local JSON lookup.

Broadcasts WebSocket ``_state`` 5 with ``nutrition`` (canonical floats) and ``result`` (string).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from config import (
    OPENAI_API_KEY,
    OPENAI_API_BASE,
    OPENAI_API_VERSION,
    OPENAI_ENGINE,
    NUTRITION_PROVIDER,
)

logger = logging.getLogger(__name__)

_client = None

NUTRITION_CANONICAL = (
    "calories",
    "protein",
    "carbs",
    "fat",
    "fiber",
    "sugar",
    "sodium",
    "cholesterol",
    "saturatedFat",
)

_ALIAS_TO_CANONICAL: dict[str, str] = {}
for _canon in NUTRITION_CANONICAL:
    _ALIAS_TO_CANONICAL[_canon.lower()] = _canon
for _alias, _canon in (
    ("calorie", "calories"),
    ("energy", "calories"),
    ("kcal", "calories"),
    ("total_calories", "calories"),
    ("protein_g", "protein"),
    ("carbohydrate", "carbs"),
    ("carbohydrates", "carbs"),
    ("total_carbohydrate", "carbs"),
    ("total_fat", "fat"),
    ("dietary_fiber", "fiber"),
    ("sugars", "sugar"),
    ("total_sugars", "sugar"),
    ("salt", "sodium"),
    ("saturated_fat", "saturatedFat"),
    ("saturatedfat", "saturatedFat"),
    ("sat_fat", "saturatedFat"),
):
    _ALIAS_TO_CANONICAL[_alias.lower()] = _canon


def _get_client():
    global _client
    if not OPENAI_API_KEY.strip():
        return None
    if _client is None:
        from openai import AzureOpenAI

        _client = AzureOpenAI(
            api_key=OPENAI_API_KEY,
            api_version=OPENAI_API_VERSION,
            azure_endpoint=OPENAI_API_BASE,
        )
    return _client


def _squash_key(name: str) -> str:
    return name.strip().lower().replace(" ", "_").replace("-", "_")


def _parse_number(val: Any) -> float | None:
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return float(val)
    s = str(val).strip()
    s = re.sub(r"[^\d.\-]", "", s)
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_answer_to_raw_dict(answer: str) -> dict[str, Any]:
    raw: dict[str, Any] = {}
    if not answer:
        return raw
    stripped = answer.strip()
    if stripped.startswith("{"):
        try:
            obj = json.loads(stripped)
            if isinstance(obj, dict):
                for k, v in obj.items():
                    raw[_squash_key(str(k))] = v
                return raw
        except json.JSONDecodeError:
            pass

    pattern = re.compile(
        r"([A-Za-z][A-Za-z _\-]+)\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*(?:g|mg|kcal|cal)?",
        re.IGNORECASE,
    )
    for m in pattern.finditer(answer):
        key = _squash_key(m.group(1))
        num = _parse_number(m.group(2))
        if key and num is not None:
            raw[key] = num
    return raw


def normalize_nutrition_dict(raw: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for k, v in raw.items():
        sk = _squash_key(str(k))
        canon = _ALIAS_TO_CANONICAL.get(sk)
        if not canon or canon in out:
            continue
        num = _parse_number(v)
        if num is None:
            continue
        out[canon] = num
    return out


async def _broadcast_state5(connections: dict, parsed: dict[str, float], source: str) -> None:
    answer_str = ", ".join(f"{k}: {v}" for k, v in sorted(parsed.items())) if parsed else ""
    payload: dict[str, Any] = {
        "_state": 5,
        "result": answer_str,
        "nutrition": parsed,
        "nutrition_source": source,
    }
    for ws in connections.values():
        await ws.send_json(payload)


async def broadcast_nutrition_clear(connections: dict) -> None:
    """Tell clients to drop nutrition text and macro cells (no food / cleared detection)."""
    await _broadcast_state5(connections, {}, "clear")


async def _nutrition_azure(food: str) -> dict[str, float]:
    client = _get_client()
    if client is None:
        return {}

    messages = [
        {
            "role": "system",
            "content": (
                "You output ONLY machine-readable nutrition for one food item. "
                "Use either (A) a single JSON object with numeric values only, keys: "
                "calories, protein, carbs, fat, fiber, sugar, sodium, cholesterol, saturatedFat "
                "(sodium and cholesterol in mg; calories in kcal; others in g unless noted). "
                "Or (B) exactly one line per nutrient: Name: value (numbers only). "
                "No other text."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Nutritional information per typical serving for: {food}. "
                "Include as many of the nine keys as reasonable estimates."
            ),
        },
    ]

    try:
        response = client.chat.completions.create(
            model=OPENAI_ENGINE,
            messages=messages,
            temperature=0.3,
            max_tokens=400,
            top_p=0.95,
            frequency_penalty=0,
            presence_penalty=0,
        )
        answer = response.choices[0].message.content or ""
    except Exception:
        logger.exception("OpenAI nutrition call failed for food=%s", food)
        return {}

    raw = _parse_answer_to_raw_dict(answer)
    parsed = normalize_nutrition_dict(raw)
    if not parsed and answer.strip():
        logger.warning("Azure nutrition parse empty for food=%s; falling back if allowed", food)
    return parsed


async def nutrition_info(food: str, connections: dict, session_id=None) -> dict:
    """
    Resolve nutrition by ``NUTRITION_PROVIDER`` and broadcast ``_state`` 5.

    - ``auto``: Azure when ``OPENAI_API_KEY`` is set, else local lookup.
    - ``azure``: Azure only (empty if no key / failure).
    - ``local``: JSON lookup only.
    - ``none``: no broadcast, returns {}.
    """
    logger.info("Nutrition for food=%s (provider=%s)", food, NUTRITION_PROVIDER)

    mode = NUTRITION_PROVIDER.strip().lower()
    if mode == "none":
        return {}

    from services.nutrition_local import lookup_nutrition_for_food

    if mode == "auto":
        if OPENAI_API_KEY.strip():
            parsed = await _nutrition_azure(food)
            if parsed:
                await _broadcast_state5(connections, parsed, "azure")
                logger.debug("Nutrition (azure) sent: %s", list(parsed.keys()))
                return parsed
        parsed = lookup_nutrition_for_food(food)
        if parsed:
            await _broadcast_state5(connections, parsed, "local")
            logger.debug("Nutrition (local fallback) keys=%s", list(parsed.keys()))
        return parsed

    if mode == "azure":
        parsed = await _nutrition_azure(food)
        if parsed:
            await _broadcast_state5(connections, parsed, "azure")
        return parsed

    if mode == "local":
        parsed = lookup_nutrition_for_food(food)
        if parsed:
            await _broadcast_state5(connections, parsed, "local")
        return parsed

    logger.warning("Unknown NUTRITION_PROVIDER=%r; use auto|azure|local|none", NUTRITION_PROVIDER)
    return {}
