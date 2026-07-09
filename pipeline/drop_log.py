# pipeline/drop_log.py
# ═══════════════════════════════════════════════════════════════
# SILENT-DROP DIAGNOSTIC LOG
#
# Every place the conversation loop consumes or rejects an utterance
# without Nova speaking appends one line here. Without this, a dropped
# turn is indistinguishable from "she didn't hear you" — the loop just
# shows "Listening" again. With it, every silent moment is auditable.
#
#   nova_data/silent_drops.jsonl
#   {"ts": "...", "kind": "echo_reject|hallucination|not_addressed|"
#                          "brain_empty|brain_error", "detail": {...}}
#
# Append-only JSONL; a write failure must never break the turn.
# ═══════════════════════════════════════════════════════════════

import json
import os
from datetime import datetime

from config import config

_PATH = os.path.join(config.NOVA_DATA_DIR, "silent_drops.jsonl")


def log(kind: str, detail: dict | None = None) -> None:
    """Record one dropped/recovered turn. Never raises."""
    try:
        os.makedirs(os.path.dirname(_PATH), exist_ok=True)
        row = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "kind": kind,
            "detail": detail or {},
        }
        with open(_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass


def recent(limit: int = 50) -> list:
    """Read the newest entries (for diagnostics)."""
    try:
        with open(_PATH, encoding="utf-8") as f:
            lines = f.readlines()[-limit:]
        return [json.loads(l) for l in lines if l.strip()]
    except Exception:
        return []
