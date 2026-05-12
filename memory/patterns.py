# memory/patterns.py
# Pattern Recognition Loop
# Once per week, surfaces one behavioral pattern observed across sessions.
# Single observation, not analysis. Does not repeat unless asked.
# Toggleable via config.PATTERN_RECOGNITION_ENABLED.

import os
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from config import config

PATTERNS_PATH = config.PATTERNS_PATH


def _load():
    try:
        with open(PATTERNS_PATH, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"observations": [], "last_generated": None, "queued": None}


def _save(data):
    os.makedirs(os.path.dirname(PATTERNS_PATH), exist_ok=True)
    with open(PATTERNS_PATH, "w") as f:
        json.dump(data, f, indent=2)


def record_session_summary(summary: dict):
    """
    Record a session summary for pattern analysis.

    summary = {
        "date": "YYYY-MM-DD",
        "start_hour": int,
        "duration_minutes": int,
        "turn_count": int,
        "primary_register": str,  # operational/reflective/creative
        "emotional_registers": list[str],
        "topics": list[str],
    }
    """
    data = _load()
    data["observations"].append(summary)
    # Keep last 90 days of observations
    cutoff = (datetime.now() - timedelta(days=90)).isoformat()
    data["observations"] = [o for o in data["observations"] if o.get("date", "") >= cutoff[:10]]
    _save(data)


def generate_weekly_pattern(timezone: str = None) -> str | None:
    """
    Analyze recent sessions and generate one pattern observation.
    Returns an observation string, or None if not enough data or already
    generated this week.
    """
    timezone = timezone or config.TIMEZONE
    data = _load()
    now = datetime.now(ZoneInfo(timezone))

    if data.get("last_generated"):
        last = datetime.fromisoformat(data["last_generated"])
        if (now - last).days < 7:
            return None

    observations = data.get("observations", [])
    if len(observations) < 3:
        return None  # need at least 3 sessions

    patterns_found = []

    # Pattern: consistent start times
    hours = [o.get("start_hour", 12) for o in observations[-7:]]
    if hours:
        avg = sum(hours) / len(hours)
        spread = max(hours) - min(hours)
        if spread <= 2:
            period = "morning" if avg < 12 else "afternoon" if avg < 17 else "evening"
            patterns_found.append(
                f"You've been consistently starting sessions in the {period}. "
                f"That seems to be your natural rhythm."
            )

    # Pattern: register tendencies
    registers = [o.get("primary_register", "") for o in observations[-7:] if o.get("primary_register")]
    if registers:
        from collections import Counter
        most_common = Counter(registers).most_common(1)[0]
        if most_common[1] >= len(registers) * 0.6:
            patterns_found.append(
                f"You've been primarily in {most_common[0]} mode across recent sessions. "
                f"That's where your energy is going."
            )

    # Pattern: emotional tendencies
    all_emotions = []
    for o in observations[-7:]:
        all_emotions.extend(o.get("emotional_registers", []))
    if all_emotions:
        from collections import Counter
        top = Counter(all_emotions).most_common(1)[0]
        if top[0] not in ("neutral", "") and top[1] >= 3:
            patterns_found.append(
                f"The register '{top[0]}' has been coming up frequently. "
                f"Something to notice."
            )

    # Pattern: session duration trends
    durations = [o.get("duration_minutes", 0) for o in observations[-7:] if o.get("duration_minutes")]
    if len(durations) >= 3:
        recent_avg = sum(durations[-3:]) / 3
        older_avg = sum(durations[:-3]) / max(1, len(durations) - 3) if len(durations) > 3 else recent_avg
        if recent_avg > older_avg * 1.5:
            patterns_found.append("Your sessions have been getting longer recently.")
        elif recent_avg < older_avg * 0.6:
            patterns_found.append("Your sessions have been shorter lately — quicker exchanges.")

    if not patterns_found:
        return None

    import random
    observation = random.choice(patterns_found)

    data["last_generated"] = now.isoformat()
    data["queued"] = observation
    _save(data)

    return observation


def get_queued_pattern() -> str | None:
    """Retrieve and clear any queued pattern observation for session start."""
    data = _load()
    queued = data.get("queued")
    if queued:
        data["queued"] = None
        _save(data)
    return queued
