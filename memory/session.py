# memory/session.py
# ═══════════════════════════════════════════════════════════════
# CONTINUOUS MEMORY — SESSION + RESTART-SAFE STATE
#
# Defines what a "session" is, persists it across restarts, and
# decides on boot whether to RESUME the prior session or START
# FRESH. Without this, Nova would either lose all context on every
# restart, or leak yesterday's topics into today's responses.
#
# Public API:
#   load_session()       → SessionState (always safe; defaults if no file)
#   save_session(state)  → atomic write
#   should_resume(state) → True if last_active is within IDLE_TIMEOUT
#   begin_session(...)   → start fresh; archive prior to journal
#   touch(state)         → update last_active_ts (call on every interaction)
#   set_marker(state, m) → set a one-line "where we are" note
#   end_session(state)   → mark ended_at; write closing journal entry
#   snapshot_history(state, history, topics) → save the live conversation
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations

import json
import os
import time
import threading
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import config


# ─── Paths ─────────────────────────────────────────────────────
SESSION_FILE = Path(config.SESSION_PATH)
SESSION_BACKUP = SESSION_FILE.with_suffix(".bak.json")

# ─── Tunables ──────────────────────────────────────────────────
IDLE_TIMEOUT_MINUTES = 240        # resume if last_active is within this window
SNAPSHOT_INTERVAL_SECONDS = 60    # how often to snapshot during operation
SNAPSHOT_MAX_HISTORY_MESSAGES = 100


_lock = threading.Lock()


# ─── State model ───────────────────────────────────────────────

@dataclass
class SessionState:
    session_id: str = ""
    started_at: float = 0.0
    last_active_ts: float = 0.0
    ended_at: Optional[float] = None
    marker: str = ""
    history: list = field(default_factory=list)
    topics: list = field(default_factory=list)
    last_snapshot_ts: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SessionState":
        return cls(
            session_id=str(d.get("session_id", "")),
            started_at=float(d.get("started_at", 0) or 0),
            last_active_ts=float(d.get("last_active_ts", 0) or 0),
            ended_at=(float(d["ended_at"]) if d.get("ended_at") else None),
            marker=str(d.get("marker", "")),
            history=list(d.get("history") or []),
            topics=list(d.get("topics") or []),
            last_snapshot_ts=float(d.get("last_snapshot_ts", 0) or 0),
        )


def _new_session_id() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H%M%S")


# ─── Persistence ───────────────────────────────────────────────

def load_session() -> SessionState:
    """Always-safe load. Returns empty SessionState if no file or corrupt."""
    if not SESSION_FILE.exists():
        return SessionState()
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return SessionState.from_dict(data)
    except Exception as e:
        print(f"[Session] load failed ({e}); preserving as backup, returning fresh.")
        try:
            SESSION_FILE.replace(SESSION_BACKUP)
        except Exception:
            pass
        return SessionState()


def save_session(state: SessionState):
    """Atomic write — write to .tmp then replace."""
    with _lock:
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = SESSION_FILE.with_suffix(".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(state.to_dict(), f, indent=2, ensure_ascii=False, default=str)
            os.replace(tmp, SESSION_FILE)
        except Exception as e:
            print(f"[Session] save failed: {e}")


# ─── Boot decision ─────────────────────────────────────────────

def should_resume(state: SessionState) -> bool:
    """True if the prior session is still 'live' (last interaction recent)."""
    if not state.session_id:
        return False
    if state.ended_at:
        return False
    if state.last_active_ts <= 0:
        return False
    idle_seconds = time.time() - state.last_active_ts
    return idle_seconds < IDLE_TIMEOUT_MINUTES * 60


def idle_minutes_since(state: SessionState) -> int:
    if state.last_active_ts <= 0:
        return -1
    return int((time.time() - state.last_active_ts) / 60)


# ─── Lifecycle ─────────────────────────────────────────────────

def begin_session(prior: Optional[SessionState] = None) -> SessionState:
    """Start a fresh session. Archive any prior unfinished session."""
    if prior and prior.session_id and not prior.ended_at:
        try:
            prior.ended_at = time.time()
            _archive_to_journal(prior, reason="auto-archived on cold start")
        except Exception as e:
            print(f"[Session] archive prior failed: {e}")

    fresh = SessionState(
        session_id=_new_session_id(),
        started_at=time.time(),
        last_active_ts=time.time(),
        ended_at=None,
        marker="",
        history=[],
        topics=[],
        last_snapshot_ts=time.time(),
    )
    save_session(fresh)
    try:
        from memory.longterm import add_journal_entry
        add_journal_entry(f"[session-start] {fresh.session_id}")
    except Exception:
        pass
    return fresh


def touch(state: SessionState):
    """Update last_active_ts on every turn."""
    state.last_active_ts = time.time()


def set_marker(state: SessionState, marker: str):
    state.marker = (marker or "").strip()[:240]
    save_session(state)


def end_session(state: SessionState, reason: str = "graceful shutdown"):
    if state.ended_at is None:
        state.ended_at = time.time()
    save_session(state)
    _archive_to_journal(state, reason=reason)


def _archive_to_journal(state: SessionState, reason: str = ""):
    try:
        from memory.longterm import add_journal_entry
        duration_min = 0
        if state.started_at and state.ended_at:
            duration_min = int((state.ended_at - state.started_at) / 60)
        marker = state.marker or "(no marker)"
        add_journal_entry(
            f"[session-end] {state.session_id} — {duration_min} min — "
            f"{marker} ({reason})"
        )
    except Exception as e:
        print(f"[Session] journal archive failed: {e}")


# ─── Snapshotting ──────────────────────────────────────────────

def snapshot_history(state: SessionState, history: list, topics: Optional[list] = None):
    """Persist current history and topics into the session state."""
    try:
        if len(history) > SNAPSHOT_MAX_HISTORY_MESSAGES:
            history = history[-SNAPSHOT_MAX_HISTORY_MESSAGES:]
        state.history = history
        if topics is not None:
            state.topics = topics
        state.last_snapshot_ts = time.time()
        save_session(state)
    except Exception as e:
        print(f"[Session] snapshot failed: {e}")


def should_snapshot(state: SessionState) -> bool:
    return (time.time() - (state.last_snapshot_ts or 0)) >= SNAPSHOT_INTERVAL_SECONDS
