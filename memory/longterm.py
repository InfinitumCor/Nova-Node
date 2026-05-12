# memory/longterm.py
# Persistent memory across Nova sessions — survives restarts.
# Stored as JSON at config.LONG_TERM_MEMORY_PATH.

import os
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from config import config

MEMORY_FILE = config.LONG_TERM_MEMORY_PATH


def _load() -> dict:
    """Load the persistent memory file."""
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"facts": [], "preferences": {}, "journal": []}
    return {"facts": [], "preferences": {}, "journal": []}


def _save(data: dict):
    """Save to the persistent memory file."""
    os.makedirs(os.path.dirname(MEMORY_FILE), exist_ok=True)
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def remember(fact: str, category: str = "general"):
    """Store a fact or observation for future sessions."""
    data = _load()
    now = datetime.now(ZoneInfo(config.TIMEZONE))
    entry = {
        "fact": fact,
        "category": category,
        "timestamp": now.isoformat(),
        "date": now.strftime("%Y-%m-%d")
    }
    existing = [f["fact"] for f in data["facts"]]
    if fact not in existing:
        data["facts"].append(entry)
        _save(data)
    return "Got it. I'll remember that."


def forget(keyword: str) -> str:
    """Remove memories matching a keyword."""
    data = _load()
    before = len(data["facts"])
    data["facts"] = [f for f in data["facts"] if keyword.lower() not in f["fact"].lower()]
    after = len(data["facts"])
    _save(data)
    removed = before - after
    if removed:
        return f"Done. I forgot {removed} thing{'s' if removed != 1 else ''} related to '{keyword}'."
    return f"I don't have anything stored about '{keyword}'."


def set_preference(key: str, value: str):
    """Store a user preference."""
    data = _load()
    data["preferences"][key] = value
    _save(data)


def get_preference(key: str) -> str:
    """Retrieve a user preference."""
    data = _load()
    return data["preferences"].get(key, "")


def add_journal_entry(entry: str):
    """Add a journal/log entry with timestamp."""
    data = _load()
    now = datetime.now(ZoneInfo(config.TIMEZONE))
    data["journal"].append({
        "entry": entry,
        "timestamp": now.isoformat(),
        "date": now.strftime("%Y-%m-%d")
    })
    _save(data)


def get_context() -> str:
    """Get all stored memory as context for Nova's prompt.

    Journal entries are filtered to the last 24 hours so that days-old
    entries can't surface as current context."""
    data = _load()
    parts = []

    if data["facts"]:
        recent_facts = data["facts"][-20:]
        facts_text = "\n".join([f"- {f['fact']} ({f['date']})" for f in recent_facts])
        parts.append(f"Things I remember about the user:\n{facts_text}")

    if data["preferences"]:
        prefs_text = "\n".join([f"- {k}: {v}" for k, v in data["preferences"].items()])
        parts.append(f"Preferences:\n{prefs_text}")

    if data["journal"]:
        cutoff = datetime.now(ZoneInfo(config.TIMEZONE)) - timedelta(hours=24)
        recent_journal = []
        for j in data["journal"][-30:]:
            try:
                ts = datetime.fromisoformat(j["timestamp"])
                if ts >= cutoff:
                    recent_journal.append(j)
            except Exception:
                continue
        if recent_journal:
            journal_text = "\n".join(
                [f"- [{j['date']}] {j['entry']}" for j in recent_journal[-5:]]
            )
            parts.append(f"Recent journal (last 24h):\n{journal_text}")

    return "\n\n".join(parts) if parts else ""


def is_remember_request(text: str) -> bool:
    """Detect if the user wants Nova to remember something."""
    keywords = [
        "remember that", "remember this", "don't forget",
        "keep in mind", "note that", "save that",
        "remember i", "remember my"
    ]
    return any(kw in text.lower() for kw in keywords)


def is_forget_request(text: str) -> bool:
    """Detect if the user wants Nova to forget something."""
    keywords = ["forget about", "forget that", "delete memory", "remove memory"]
    return any(kw in text.lower() for kw in keywords)
