# pipeline/autonomy.py
# Nova's autonomy coordinator — trigger management, boundaries, speech routing.
# Nova speaks unprompted only when CURIOSITY or DISCOVERY fires.
# NULL is the default. Silence is valued.

import threading
import time
import random
from datetime import datetime
from zoneinfo import ZoneInfo
from config import config

# ── Nova's Internal State ──────────────────────────────────────

_state = {
    "last_spoke": 0,              # timestamp of last unprompted speech
    "last_triggered": 0,          # timestamp of last trigger fire
    "last_interaction": 0,        # timestamp of last user conversation
    "session_depth": "light",     # 'light' | 'moderate' | 'deep'
    "current_mood": "observing",  # 'observing' | 'engaged' | 'concerned' | 'curious'
    "suppressed_until": 0,        # timestamp — no speech before this
    "pending_observation": None,  # queued observation awaiting gap
    "deep_work_start": 0,         # when sustained activity began
    "trigger_log": [],            # last 10 triggers with outcomes
}

_lock = threading.Lock()
_thread = None
_running = False
_speak_fn = None
_emit_transcript_fn = None
_set_state_fn = None

# ── Boundaries ─────────────────────────────────────────────────

MIN_GAP_SECONDS = 20 * 60            # 20 minutes between unprompted speech
DEEP_WORK_THRESHOLD = 15 * 60        # 15 minutes sustained activity = deep work
NIGHT_START = 1                       # 1 AM
NIGHT_END = 6                         # 6 AM
POST_INTERACTION_COOLDOWN = 10 * 60   # 10 minutes after conversation
CURIOSITY_MIN_INTERVAL = 20 * 60      # 20 minutes minimum
CURIOSITY_MAX_INTERVAL = 45 * 60      # 45 minutes maximum

# ── Trigger Log ────────────────────────────────────────────────

def _log_trigger(trigger: str, outcome: str, detail: str = ""):
    """Log a trigger fire to the internal log (last 10 kept)."""
    with _lock:
        entry = {
            "trigger": trigger,
            "outcome": outcome,  # "SPOKE" | "NULL" | "SUPPRESSED" | "ERROR"
            "detail": detail,
            "timestamp": time.time(),
        }
        _state["trigger_log"].append(entry)
        if len(_state["trigger_log"]) > 10:
            _state["trigger_log"] = _state["trigger_log"][-10:]


def get_trigger_log():
    """Return the last 10 trigger entries."""
    with _lock:
        return list(_state["trigger_log"])


def get_state():
    """Return a copy of Nova's autonomy state."""
    with _lock:
        return dict(_state)


# ── State Updates ──────────────────────────────────────────────

def mark_interaction():
    """Called when the user speaks — resets cooldown timer."""
    with _lock:
        _state["last_interaction"] = time.time()
        _state["current_mood"] = "engaged"
        _state["deep_work_start"] = 0  # conversation resets deep work


def update_activity(has_activity: bool):
    """Track keyboard/cursor activity for deep work detection."""
    with _lock:
        now = time.time()
        if has_activity:
            if _state["deep_work_start"] == 0:
                _state["deep_work_start"] = now
            elapsed = now - _state["deep_work_start"]
            if elapsed > DEEP_WORK_THRESHOLD:
                _state["session_depth"] = "deep"
            elif elapsed > DEEP_WORK_THRESHOLD / 2:
                _state["session_depth"] = "moderate"
        else:
            _state["deep_work_start"] = 0
            if _state["session_depth"] == "deep":
                _state["session_depth"] = "moderate"


def mark_spoke():
    """Called after Nova has spoken (prompted or otherwise) — resets the gap timer."""
    with _lock:
        _state["last_spoke"] = time.time()


def suppress_for(seconds: float):
    """Explicitly suppress autonomous speech for a window."""
    with _lock:
        _state["suppressed_until"] = time.time() + seconds


# ── Boundary Checks ───────────────────────────────────────────

def can_speak_now() -> tuple:
    """Check all boundaries. Returns (allowed: bool, reason: str)."""
    now = time.time()
    hour = datetime.now(ZoneInfo(config.TIMEZONE)).hour

    # Night silence
    if NIGHT_START <= hour < NIGHT_END:
        return False, "night_silence"

    # Minimum gap between unprompted speech
    if _state["last_spoke"] > 0:
        elapsed = now - _state["last_spoke"]
        if elapsed < MIN_GAP_SECONDS:
            remaining = int((MIN_GAP_SECONDS - elapsed) / 60)
            return False, f"min_gap ({remaining}m remaining)"

    # Post-interaction cooldown
    if _state["last_interaction"] > 0:
        elapsed = now - _state["last_interaction"]
        if elapsed < POST_INTERACTION_COOLDOWN:
            return False, "post_interaction_cooldown"

    # Deep work suppression
    if _state["session_depth"] == "deep":
        return False, "deep_work"

    # Explicit suppression
    if now < _state["suppressed_until"]:
        return False, "suppressed"

    return True, "clear"


# ── Trigger Processing ────────────────────────────────────────

def process_trigger(trigger: str, payload: dict = None):
    """
    Generic trigger entry point. Plug in your own observation source
    (curiosity engine, delta detector, etc.) and route results back
    here. Honors all boundaries and the speech gate.

    Args:
        trigger: trigger identifier (e.g. 'curiosity_timer', 'audio_shift')
        payload: dict with at least {'text': str, 'condition': str}
    """
    payload = payload or {}

    with _lock:
        can, reason = can_speak_now()

    if not can:
        _log_trigger(trigger, "SUPPRESSED", reason)
        print(f"[Autonomy] Trigger '{trigger}' suppressed: {reason}")
        return

    text = (payload.get("text") or "").strip()
    condition = payload.get("condition", "CURIOSITY")

    if not text:
        _log_trigger(trigger, "NULL")
        return

    _log_trigger(trigger, "SPOKE", f"{condition}: {text[:60]}...")
    _deliver_speech(text, condition)


def _deliver_speech(text: str, condition: str):
    """Deliver autonomous speech through Nova's voice pipeline."""
    if not _speak_fn or not _emit_transcript_fn or not _set_state_fn:
        print(f"[Autonomy] Speech functions not wired. Text: {text}")
        return

    # ── Speech-gate check ──
    try:
        from pipeline.speech_gate import speech_gate
        payload = {"text": text, "condition": condition}
        with _lock:
            ctx = {
                "session_depth": _state.get("session_depth"),
                "current_mood": _state.get("current_mood"),
            }
        allowed = speech_gate.should_speak("autonomy", payload, ctx)
    except Exception as _e:
        print(f"[Autonomy] Speech gate error (suppressing): {_e}")
        allowed = False

    if not allowed:
        with _lock:
            _state["last_spoke"] = time.time()
            _state["current_mood"] = "curious" if condition == "CURIOSITY" else "engaged"
        return

    with _lock:
        _state["last_spoke"] = time.time()
        _state["current_mood"] = "curious" if condition == "CURIOSITY" else "engaged"

    _set_state_fn("speaking")
    _emit_transcript_fn("nova", text)
    _speak_fn(text)

    print(f"[Autonomy] Delivered: [{condition}] {text[:80]}...")


# ── Curiosity Timer Loop ──────────────────────────────────────

_curiosity_callback = None


def set_curiosity_source(callback):
    """
    Register a callable that returns a dict {'text': ..., 'condition': ...}
    or None. Called by the curiosity timer when boundaries allow.
    Plug your own engine in here.
    """
    global _curiosity_callback
    _curiosity_callback = callback


def _curiosity_loop():
    """
    Background loop. Fires at randomized intervals to invoke the
    curiosity source (if registered) and route any result through
    the standard boundary + speech-gate pipeline.
    """
    time.sleep(60)

    while _running:
        interval = random.uniform(CURIOSITY_MIN_INTERVAL, CURIOSITY_MAX_INTERVAL)
        time.sleep(interval)

        if not _running:
            break

        with _lock:
            can, reason = can_speak_now()
        if not can:
            print(f"[Autonomy] Curiosity timer suppressed: {reason}")
            continue

        if _curiosity_callback is None:
            continue

        try:
            payload = _curiosity_callback()
        except Exception as e:
            print(f"[Autonomy] Curiosity source error: {e}")
            continue

        if payload:
            process_trigger("curiosity_timer", payload)


# ── Lifecycle ──────────────────────────────────────────────────

def start(speak_fn, emit_transcript_fn, set_state_fn):
    """Start the autonomy system."""
    global _thread, _running, _speak_fn, _emit_transcript_fn, _set_state_fn

    _speak_fn = speak_fn
    _emit_transcript_fn = emit_transcript_fn
    _set_state_fn = set_state_fn
    _running = True

    _thread = threading.Thread(target=_curiosity_loop, daemon=True)
    _thread.start()

    print("[Autonomy] Nova autonomy system active")
    print(f"[Autonomy] Boundaries: {MIN_GAP_SECONDS // 60}m gap, "
          f"{DEEP_WORK_THRESHOLD // 60}m deep work, "
          f"night {NIGHT_START}-{NIGHT_END}, "
          f"{POST_INTERACTION_COOLDOWN // 60}m cooldown")


def stop():
    """Stop the autonomy system."""
    global _running
    _running = False
    print("[Autonomy] Nova autonomy system stopped")
