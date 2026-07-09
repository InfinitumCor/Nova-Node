# initiation/selectors.py
# Question selection logic for each register.

import os
import json
import random

from initiation.memory_interface import get_answered_ids

_POOLS_DIR = os.path.join(os.path.dirname(__file__), "pools")


def _load_pool(filename: str) -> list[dict]:
    """Load a question pool from JSON. Filters out placeholder/comment entries."""
    path = os.path.join(_POOLS_DIR, filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        # Skip entries that look like placeholder comments
        return [q for q in raw if isinstance(q, dict) and "id" in q and "text" in q]
    except Exception as e:
        print(f"[Initiation] Failed to load pool {filename}: {e}")
        return []


def pick_idle_question() -> dict | None:
    """Select a random unanswered question from the idle pool."""
    pool = _load_pool("idle.json")
    answered = get_answered_ids()
    candidates = [q for q in pool if q["id"] not in answered]
    if not candidates:
        return None
    return random.choice(candidates)


def pick_reflective_question() -> dict | None:
    """Select a random unanswered question from the reflective pool."""
    pool = _load_pool("reflective.json")
    answered = get_answered_ids()
    candidates = [q for q in pool if q["id"] not in answered]
    if not candidates:
        return None
    return random.choice(candidates)
