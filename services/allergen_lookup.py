"""
services/allergen_lookup.py – Phase 6: Local allergen lookup service.

Checks whether a detected food item contains any of the child's declared
allergens using a curated local JSON map (data/allergen_map.json).

Lookup strategy:
  1. Exact match on food slug in allergen_map.json
  2. Substring match: if map key is contained in the food name (or vice-versa)
  3. Returns empty list (no alert) when food is unknown — silent fail safe.

Returns a list of allergen names (strings from master_allergens.name) that
are present in the detected food.
"""

from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)

_ALLERGEN_MAP_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "allergen_map.json",
)

# Canonical Big-9 aliases → normalised name used in allergen_map.json
_ALIAS_NORMALISE: dict[str, str] = {
    # milk / dairy
    "dairy":          "milk",
    "lactose":        "milk",
    "casein":         "milk",
    # egg
    "eggs":           "egg",
    # peanut
    "peanuts":        "peanut",
    "groundnut":      "peanut",
    "groundnuts":     "peanut",
    # tree nut
    "treenut":        "tree nut",
    "tree nuts":      "tree nut",
    "nuts":           "tree nut",
    "nut":            "tree nut",
    # soy
    "soya":           "soy",
    "soybeans":       "soy",
    "soybean":        "soy",
    # wheat / gluten
    "wheat":          "wheat",
    "gluten":         "wheat",
    "flour":          "wheat",
    # fish
    # shellfish
    "crustacean":     "shellfish",
    "crustaceans":    "shellfish",
    "mollusc":        "shellfish",
    "molluscs":       "shellfish",
    # sesame
    "sesame":         "sesame",
    "sesame seed":    "sesame",
}


@lru_cache(maxsize=1)
def _load_allergen_map() -> dict[str, list[str]]:
    """Load and cache allergen_map.json.  Returns {} on any error."""
    path = _ALLERGEN_MAP_PATH
    if not os.path.isfile(path):
        logger.warning("Allergen map not found at %s — allergen matching disabled", path)
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            raw: dict[str, Any] = json.load(f)
    except Exception:
        logger.exception("Failed to load allergen map: %s", path)
        return {}
    # Strip the meta key
    raw.pop("__meta__", None)
    result: dict[str, list[str]] = {}
    for food_key, allergens in raw.items():
        if isinstance(allergens, list):
            result[food_key.lower().strip()] = [str(a).lower().strip() for a in allergens]
    logger.info("Allergen map loaded: %d food entries", len(result))
    return result


def preload_allergen_cache() -> None:
    """Call at startup to warm the in-memory cache (avoids first-request load)."""
    _load_allergen_map()


def clear_allergen_cache() -> None:
    """For testing / hot-reload after editing allergen_map.json."""
    _load_allergen_map.cache_clear()


def _normalise_allergen(name: str) -> str:
    """Canonicalise user-declared intolerance strings to map keys."""
    key = name.lower().strip()
    return _ALIAS_NORMALISE.get(key, key)


def _normalise_food(food: str) -> str:
    return (food or "").lower().strip().replace("_", " ").replace("-", " ")


def _find_food_allergens(food_name: str) -> list[str]:
    """
    Return the list of allergen names present in food_name.

    Matching order:
      1. Exact slug lookup
      2. Any map key contained in the food name  (e.g. map key "peanut" in "peanut butter")
      3. The food name contained in any map key  (e.g. food "tuna" in map key "tuna salad")
    Returns [] when the food is not in the map (safe default).
    """
    allergen_map = _load_allergen_map()
    if not allergen_map:
        return []

    slug = _normalise_food(food_name)
    if not slug:
        return []

    # 1. Exact match
    if slug in allergen_map:
        return list(allergen_map[slug])

    # 2. Map key contained in slug ("peanut" in "peanut butter cookie")
    best_key = ""
    for key in allergen_map:
        if key in slug and len(key) > len(best_key):
            best_key = key
    if best_key:
        return list(allergen_map[best_key])

    # 3. Slug contained in map key ("apple" → "apple pie")
    for key, allergens in allergen_map.items():
        if slug in key:
            return list(allergens)

    # Unknown food — return empty list (no false positives)
    logger.debug("Allergen map: no entry for food=%r", food_name)
    return []


def check_food_allergens(
    food_name: str,
    declared_allergen_names: list[str],
) -> list[str]:
    """
    Synchronous check: which of the child's declared allergens are present
    in the detected food?

    Parameters
    ----------
    food_name : str
        The detected food label (e.g. "pizza", "peanut butter").
    declared_allergen_names : list[str]
        The child's allergy profile as plain strings (e.g. ["milk", "peanut"]).

    Returns
    -------
    list[str]
        Matched allergen names (subset of declared_allergen_names), lowercased.
        Empty list means no allergen detected or food unknown.
    """
    if not food_name or not declared_allergen_names:
        return []

    food_allergens = _find_food_allergens(food_name)
    if not food_allergens:
        # Custom / unmapped foods (e.g. user-added "Banana"): match declared name to food label.
        slug = _normalise_food(food_name)
        declared_normalised = {_normalise_allergen(n) for n in declared_allergen_names if n}
        direct: list[str] = []
        for declared in declared_allergen_names:
            if not declared:
                continue
            key = _normalise_food(str(declared))
            norm = _normalise_allergen(str(declared))
            if key and slug and (key == slug or key in slug or slug in key):
                direct.append(norm if norm in declared_normalised else str(declared).lower().strip())
            elif norm and norm in slug:
                direct.append(norm)
        if direct:
            logger.info(
                "[ALLERGEN] Direct food-name match: food=%r declared=%s → %s",
                food_name,
                declared_allergen_names,
                direct,
            )
            return direct
        return []

    # Normalise declared names for comparison
    declared_normalised = {_normalise_allergen(n) for n in declared_allergen_names if n}

    matched: list[str] = []
    for allergen in food_allergens:
        # Check both the raw allergen name and normalised version
        if allergen in declared_normalised or _normalise_allergen(allergen) in declared_normalised:
            matched.append(allergen)

    if matched:
        logger.info(
            "[ALLERGEN] Food=%r → allergens in map: %s | declared: %s | matched: %s",
            food_name,
            food_allergens,
            list(declared_normalised),
            matched,
        )
    return matched
