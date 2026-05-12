# initiation/contextual.py
# Dynamically generates contextual questions anchored to known user facts.
# Uses Claude (same as the main brain).

import random

import anthropic

from config import config
from initiation.memory_interface import (
    get_all_facts,
    days_since_anchor_asked,
    mark_anchor_asked,
)


_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


def _llm_generate(prompt: str, max_tokens: int = 100) -> str:
    """Generate a single response from Claude."""
    try:
        resp = _get_client().messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(
            b.text for b in resp.content if getattr(b, "type", "") == "text"
        ).strip()
    except Exception as e:
        print(f"[Initiation/Contextual] LLM error: {e}")
        return ""


def find_fresh_anchors(cooldown_days: int = 14) -> list[tuple[str, str]]:
    """
    Find anchors (user facts) that haven't been asked about recently.
    Returns list of (anchor_key, fact_value) tuples.
    """
    facts = get_all_facts()
    if not facts:
        return []

    fresh = []
    for key, entry in facts.items():
        days = days_since_anchor_asked(key)
        if days >= cooldown_days:
            fresh.append((key, entry["value"]))

    return fresh


def generate_contextual_question(anchor_key: str, anchor_value: str) -> dict | None:
    """
    Generate a single contextual question anchored to a known fact about the user.
    Returns a question dict compatible with the idle pool format, or None on failure.
    """
    prompt = (
        f"Given this fact about the user: {anchor_key} — {anchor_value}\n\n"
        "Write one short, curious, low-pressure question related to this. "
        "No preamble. Conversational, not interview. "
        "The question should feel like something a close companion would ask "
        "during a quiet moment. One sentence only."
    )

    text = _llm_generate(prompt, max_tokens=80)
    if not text:
        return None

    text = text.strip('"').strip("'").strip()
    if not text:
        return None

    mark_anchor_asked(anchor_key)

    return {
        "id": f"contextual_{anchor_key}",
        "text": text,
        "weight": "light",
        "anchor": anchor_key,
    }


def pick_contextual_question(cooldown_days: int = 14) -> dict | None:
    """
    Full contextual question selection: find a fresh anchor, generate a question.
    Returns a question dict or None if no anchors available.
    """
    anchors = find_fresh_anchors(cooldown_days)
    if not anchors:
        return None

    anchor_key, anchor_value = random.choice(anchors)
    return generate_contextual_question(anchor_key, anchor_value)
