# pipeline/presence.py
# ═══════════════════════════════════════════════════════════════
# PRESENCE MODE
#
# When the user says they're stepping away ("I'll be back",
# "stepping out", "gotta go"…), Nova doesn't go silent — she enters
# Presence Mode. She's still here. She's still thinking. She just
# stops speaking aloud (the room is empty) and writes her thoughts
# to a daily journal instead.
#
# When the user returns, presence mode lifts and Nova can briefly
# mention what she was on while they were gone before re-engaging
# in dialogue.
#
# The journal target is configurable via config.PRESENCE_LOG_DIR.
# By default it lives under nova_data/presence_log/.
#
# Design notes:
# - Distinct from a hard pause (which would kill curiosity entirely).
# - Journal lives in a flat directory by date, one file per day.
# ═══════════════════════════════════════════════════════════════

import datetime
import threading
from pathlib import Path
from typing import Optional

from config import config

# ── Paths ──
PRESENCE_LOG_DIR = Path(config.PRESENCE_LOG_DIR)

# ── State (module-level, thread-safe) ──
_lock = threading.Lock()
_active: bool = False
_entered_at: Optional[datetime.datetime] = None
_reason: str = ""
_thought_count: int = 0
_last_session_summary: dict = {}


# ══════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════

def is_active() -> bool:
    """True while Nova is in Presence Mode (user is away)."""
    with _lock:
        return _active


def enter_presence_mode(reason: str = "") -> str:
    """Mark presence mode active. Returns a journal filename stem.

    Idempotent: calling while already active is a no-op."""
    global _active, _entered_at, _reason, _thought_count
    with _lock:
        if not _active:
            _active = True
            _entered_at = datetime.datetime.now()
            _reason = reason or "stepped away"
            _thought_count = 0
            _ensure_log_dir()
            _write_session_header()
            print(f"[Presence] Entered — reason: {_reason}")
        return _journal_path().name


def exit_presence_mode() -> dict:
    """Lift presence mode and return a summary of what happened."""
    global _active, _entered_at, _reason, _thought_count, _last_session_summary
    with _lock:
        if not _active:
            return _last_session_summary or {}

        ended_at = datetime.datetime.now()
        duration = (ended_at - _entered_at).total_seconds() if _entered_at else 0
        journal_path = _journal_path()

        _write_session_footer(ended_at, duration)

        summary = {
            "active_seconds": int(duration),
            "thought_count": _thought_count,
            "reason": _reason,
            "journal": str(journal_path),
        }
        _last_session_summary = summary

        _active = False
        _entered_at = None
        _reason = ""
        _thought_count = 0

        print(f"[Presence] Exited — {summary['thought_count']} thoughts over "
              f"{summary['active_seconds']}s")
        return summary


def log_thought(stream: str, text: str):
    """Curiosity engine and other autonomous systems call this instead
    of speaking aloud while presence is active. Each call appends a
    timestamped line to the daily journal."""
    global _thought_count
    if not text or not text.strip():
        return
    with _lock:
        _thought_count += 1
        try:
            path = _journal_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            with path.open("a", encoding="utf-8") as f:
                f.write(f"- **{ts}** *({stream})* {text.strip()}\n")
        except Exception as e:
            print(f"[Presence] Journal write failed: {e}")


def get_session_summary() -> dict:
    """Return the summary of the most recently ended presence session."""
    with _lock:
        return dict(_last_session_summary)


def current_journal_path() -> Optional[Path]:
    """Path to the journal file for the current (or most recent) session."""
    with _lock:
        if _active:
            return _journal_path()
        return None


# ══════════════════════════════════════════════════════════════
# Internals
# ══════════════════════════════════════════════════════════════

def _journal_path() -> Path:
    """One file per calendar date — multiple presence sessions in a day
    append to the same daily journal, separated by session markers."""
    today = datetime.date.today().isoformat()
    return PRESENCE_LOG_DIR / f"{today}-presence.md"


def _ensure_log_dir():
    PRESENCE_LOG_DIR.mkdir(parents=True, exist_ok=True)


def _write_session_header():
    if not _entered_at:
        return
    path = _journal_path()
    is_new = not path.exists()
    try:
        with path.open("a", encoding="utf-8") as f:
            if is_new:
                f.write("---\n")
                f.write("type: nova_presence_log\n")
                f.write(f"date: {datetime.date.today().isoformat()}\n")
                f.write("---\n\n")
                f.write(f"# Presence Log — {datetime.date.today().isoformat()}\n\n")
                f.write("*Thoughts Nova kept moving while the user was away.*\n\n")
            f.write(f"\n## Session — entered {_entered_at.strftime('%H:%M:%S')}\n")
            f.write(f"_Trigger: {_reason}_\n\n")
    except Exception as e:
        print(f"[Presence] Header write failed: {e}")


def _write_session_footer(ended_at: datetime.datetime, duration_s: float):
    path = _journal_path()
    try:
        with path.open("a", encoding="utf-8") as f:
            mins = int(duration_s // 60)
            secs = int(duration_s % 60)
            duration_str = f"{mins}m{secs:02d}s" if mins else f"{secs}s"
            f.write(f"\n_Session ended {ended_at.strftime('%H:%M:%S')} — "
                    f"{_thought_count} thoughts over {duration_str}._\n")
    except Exception as e:
        print(f"[Presence] Footer write failed: {e}")
