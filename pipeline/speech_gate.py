# pipeline/speech_gate.py
# =================================================================
# Central speech-gate. Single point of arbitration for all unprompted
# speech sources. Direct-response paths (user-addressed Nova replies)
# do NOT route through this gate — they continue to flow through the
# normal conversational pipeline.
#
# Deny-all by default for unprompted sources. Explicit allow rules
# can be registered per source. Every gate decision (source, decision,
# reason, payload) is logged to gate_log/<date>.jsonl so the silent
# phase remains auditable.
# =================================================================

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime
from typing import Any, Optional

from config import config

logger = logging.getLogger(__name__)


# ── Source registry ───────────────────────────────────────────────
#
# Each source string is what callers pass to should_speak(). Adding
# a new source here is the canonical way to register a new unprompted
# speaker; unknown sources fall through to the default (deny).

ALLOW_SOURCES: set[str] = set()
"""Sources whose unprompted speech is currently permitted.
Add a source string here once you've reviewed it for safety/UX."""

DENY_SOURCES: set[str] = {
    "curiosity_engine",
    "initiation_engine",
    "autonomy",
}
"""Sources known to exist but currently muted."""


# ── Gate log ──────────────────────────────────────────────────────
#
# Append-only JSONL per day. Records every gate decision and, for
# denials, the full payload Nova would have voiced.

_LOG_DIR = os.path.join(config.NOVA_DATA_DIR, "gate_log")

_log_lock = threading.Lock()


def _log_path() -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    return os.path.join(_LOG_DIR, f"{today}.jsonl")


def _ensure_log_dir() -> None:
    try:
        os.makedirs(_LOG_DIR, exist_ok=True)
    except Exception as e:
        logger.debug(f"speech_gate: log dir create failed ({e})")


def _write_log(entry: dict[str, Any]) -> None:
    """Append a single decision entry to the day's JSONL file."""
    _ensure_log_dir()
    line = json.dumps(entry, ensure_ascii=False, default=str)
    try:
        with _log_lock, open(_log_path(), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as e:
        logger.debug(f"speech_gate: log write failed ({e})")


# ── Public API ────────────────────────────────────────────────────


class SpeechGate:
    """
    Central arbiter for unprompted speech.

    Usage (from any unprompted-speech source):

        from pipeline.speech_gate import speech_gate
        if not speech_gate.should_speak('curiosity_engine', payload, ctx):
            # Suppress the spoken output. Internal cognition continues.
            return

    Direct-response paths (user-addressed Nova replies) should NOT
    call this method — they bypass the gate entirely.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, dict[str, int]] = {}

    # ── Primary method ────────────────────────────────────────────

    def should_speak(
        self,
        source: str,
        payload: Optional[dict[str, Any]] = None,
        context: Optional[dict[str, Any]] = None,
    ) -> bool:
        """
        Return True if speech from `source` should be voiced, False if
        it should be suppressed. Always logs the decision.
        """
        payload = payload or {}
        context = context or {}

        decision, reason = self._decide(source)

        with self._lock:
            bucket = self._counts.setdefault(source, {"allow": 0, "deny": 0})
            bucket["allow" if decision else "deny"] += 1

        entry: dict[str, Any] = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "source": source,
            "decision": "allow" if decision else "deny",
            "reason": reason,
            "payload": payload,
            "context": context,
        }
        _write_log(entry)

        try:
            text_preview = ""
            if isinstance(payload, dict):
                t = payload.get("text") or payload.get("thought") or ""
                if isinstance(t, str):
                    text_preview = t[:60].replace("\n", " ")
            logger.info(
                f"[gate] {source} -> {entry['decision']} ({reason}) "
                f"{('| ' + text_preview) if text_preview else ''}"
            )
        except Exception:
            pass

        return decision

    # ── Decision logic ────────────────────────────────────────────

    def _decide(self, source: str) -> tuple[bool, str]:
        """
        Deny-all by default. Explicit allow rules per source.
        Unknown sources default to deny so a forgotten registration
        never accidentally permits unprompted speech.
        """
        if source in ALLOW_SOURCES:
            return True, "allow_listed"
        if source in DENY_SOURCES:
            return False, "deny_listed"
        return False, "unknown_source_default_deny"

    # ── Mutation API ──────────────────────────────────────────────

    def allow(self, source: str) -> None:
        """Move a source to the allow list (and remove from deny if present)."""
        ALLOW_SOURCES.add(source)
        DENY_SOURCES.discard(source)

    def deny(self, source: str) -> None:
        """Move a source to the deny list (and remove from allow if present)."""
        DENY_SOURCES.add(source)
        ALLOW_SOURCES.discard(source)

    # ── Diagnostics ───────────────────────────────────────────────

    def get_counts(self) -> dict[str, dict[str, int]]:
        """Return a copy of per-source allow/deny counters."""
        with self._lock:
            return {k: dict(v) for k, v in self._counts.items()}

    def reset_counts(self) -> None:
        with self._lock:
            self._counts.clear()


# ── Module-level singleton ────────────────────────────────────────

speech_gate = SpeechGate()


__all__ = ["SpeechGate", "speech_gate", "ALLOW_SOURCES", "DENY_SOURCES"]
