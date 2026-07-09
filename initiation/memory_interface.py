# initiation/memory_interface.py
# Bridge between the initiation engine and persistent memory.

import json
import os
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

from config import config

# Initiation state lives alongside long-term memory but in its own keys.
INIT_STATE_FILE = os.path.join(config.NOVA_DATA_DIR, "initiation_state.json")

_lock = threading.Lock()


def _load() -> dict:
    """Load the initiation state file."""
    with _lock:
        if os.path.exists(INIT_STATE_FILE):
            try:
                with open(INIT_STATE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    return {"answered_questions": {}, "user_facts": {}, "anchor_last_asked": {}}


def _save(data: dict):
    """Save the initiation state file."""
    with _lock:
        os.makedirs(os.path.dirname(INIT_STATE_FILE), exist_ok=True)
        with open(INIT_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


# ── Answered Questions ────────────────────────────────────────────

def is_answered(question_id: str) -> bool:
    """Check if a question has already been answered."""
    return question_id in _load()["answered_questions"]


def get_answered_ids() -> set:
    """Return the set of all answered question IDs."""
    return set(_load()["answered_questions"].keys())


def mark_answered(question_id: str, answer: str, register: str):
    """Mark a question as answered and store the response."""
    data = _load()
    now = datetime.now(ZoneInfo(config.TIMEZONE))
    data["answered_questions"][question_id] = {
        "answer": answer,
        "register": register,
        "timestamp": now.isoformat(),
    }
    _save(data)


# ── User Facts ────────────────────────────────────────────────────

def store_fact(anchor_key: str, value: str, source_question_id: str = ""):
    """
    Store a fact about the user, available as a contextual anchor
    and as implicit reference material across other systems.
    """
    data = _load()
    now = datetime.now(ZoneInfo(config.TIMEZONE))
    data["user_facts"][anchor_key] = {
        "value": value,
        "source_question_id": source_question_id,
        "timestamp": now.isoformat(),
    }
    _save(data)

    # Mirror to longterm memory for cross-system visibility.
    try:
        from memory.longterm import remember
        remember(f"{anchor_key}: {value}", category="initiation_fact")
    except Exception:
        pass


def get_all_facts() -> dict:
    """Return all stored user facts."""
    return dict(_load()["user_facts"])


def get_fact(anchor_key: str) -> str:
    """Get a single fact value by anchor key."""
    entry = _load()["user_facts"].get(anchor_key, {})
    return entry.get("value", "")


# ── Anchor Freshness ──────────────────────────────────────────────

def mark_anchor_asked(anchor_key: str):
    """Record that we asked about this anchor."""
    data = _load()
    now = datetime.now(ZoneInfo(config.TIMEZONE))
    data["anchor_last_asked"][anchor_key] = now.isoformat()
    _save(data)


def get_anchor_last_asked(anchor_key: str) -> datetime | None:
    """Return the datetime an anchor was last asked about, or None."""
    ts = _load()["anchor_last_asked"].get(anchor_key)
    if ts:
        try:
            return datetime.fromisoformat(ts)
        except Exception:
            return None
    return None


def days_since_anchor_asked(anchor_key: str) -> int:
    """Return days since this anchor was last asked. 9999 if never."""
    last = get_anchor_last_asked(anchor_key)
    if last is None:
        return 9999
    now = datetime.now(ZoneInfo(config.TIMEZONE))
    return (now - last).days


# ── Fact Context for Other Systems ────────────────────────────────

def get_facts_context() -> str:
    """
    Return all user facts formatted as context string.
    Intended to be injected into Nova's prompt alongside longterm memory.
    """
    facts = get_all_facts()
    if not facts:
        return ""
    lines = [f"- {key}: {entry['value']}" for key, entry in facts.items()]
    return "Things I know about the user (from our conversations):\n" + "\n".join(lines)
