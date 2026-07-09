# pipeline/delta_detector.py
# =================================================================
# Delta detector — polls registered "grounding sources" on a schedule,
# diffs their current snapshot against the persisted previous one,
# and emits structured Delta records when meaningful change is found.
#
# Public release ships with NO built-in sources. Register your own
# source by calling register_source(name, snapshot_fn, diff_fn).
#
#   snapshot_fn() -> dict   (current view of the source)
#   diff_fn(prev, cur) -> list[dict]   (zero or more delta records)
#
# State persists between restarts to config.DELTA_STATE_PATH so a
# restart doesn't burst the curiosity engine with "everything looks
# new".
# =================================================================

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from config import config

# ── Source registry ───────────────────────────────────────────────

@dataclass
class Source:
    name: str
    snapshot_fn: Callable[[], Dict[str, Any]]
    diff_fn: Callable[[Dict[str, Any], Dict[str, Any]], List[Dict[str, Any]]]
    enabled: bool = True
    last_polled_ts: float = 0.0


_sources: Dict[str, Source] = {}
_lock = threading.Lock()


def register_source(name: str,
                    snapshot_fn: Callable[[], Dict[str, Any]],
                    diff_fn: Callable[[Dict[str, Any], Dict[str, Any]],
                                      List[Dict[str, Any]]]) -> None:
    """Register a source with snapshot + diff callables."""
    with _lock:
        _sources[name] = Source(
            name=name,
            snapshot_fn=snapshot_fn,
            diff_fn=diff_fn,
        )


def unregister_source(name: str) -> None:
    with _lock:
        _sources.pop(name, None)


# ── State persistence ─────────────────────────────────────────────

def _load_state() -> dict:
    path = config.DELTA_STATE_PATH
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    path = config.DELTA_STATE_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2, default=str)
        os.replace(tmp, path)
    except Exception as e:
        print(f"[delta_detector] save state failed: {e}")


# ── Polling ───────────────────────────────────────────────────────

def poll_once() -> List[Dict[str, Any]]:
    """
    Snapshot every enabled source, diff against the persisted previous
    snapshot, return a flat list of delta records. Persists the new
    snapshot for next time.
    """
    state = _load_state()
    deltas: List[Dict[str, Any]] = []
    now = time.time()

    with _lock:
        names = list(_sources.keys())

    for name in names:
        with _lock:
            src = _sources.get(name)
        if not src or not src.enabled:
            continue

        try:
            current = src.snapshot_fn() or {}
        except Exception as e:
            print(f"[delta_detector] {name} snapshot failed: {e}")
            continue

        previous = state.get(name)
        if previous is not None:
            try:
                source_deltas = src.diff_fn(previous, current) or []
            except Exception as e:
                print(f"[delta_detector] {name} diff failed: {e}")
                source_deltas = []
            for d in source_deltas:
                d.setdefault("source", name)
                d.setdefault("detected_at", now)
                deltas.append(d)

        state[name] = current
        src.last_polled_ts = now

    if state:
        _save_state(state)

    return deltas


# ── Background loop ───────────────────────────────────────────────

_thread: Optional[threading.Thread] = None
_running = False
POLL_INTERVAL_SECONDS = 5 * 60


def _loop(callback: Callable[[List[Dict[str, Any]]], None]):
    while _running:
        try:
            deltas = poll_once()
            if deltas and callback:
                try:
                    callback(deltas)
                except Exception as e:
                    print(f"[delta_detector] callback error: {e}")
        except Exception as e:
            print(f"[delta_detector] loop error: {e}")
        time.sleep(POLL_INTERVAL_SECONDS)


def start(callback: Callable[[List[Dict[str, Any]]], None]) -> None:
    """Start the background polling loop."""
    global _thread, _running
    if _running:
        return
    _running = True
    _thread = threading.Thread(target=_loop, args=(callback,), daemon=True)
    _thread.start()
    print(f"[delta_detector] started — polling every {POLL_INTERVAL_SECONDS}s")


def stop() -> None:
    global _running
    _running = False
