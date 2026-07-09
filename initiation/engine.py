# initiation/engine.py
# Nova's layered initiation engine — core loop.
# Runs alongside the curiosity engine. Speaks first only when all
# silence-respecting gates allow it.

import os
import time
import random
import threading
import json
from datetime import datetime, date
from zoneinfo import ZoneInfo

from config import config
from initiation.selectors import pick_idle_question, pick_reflective_question
from initiation.contextual import pick_contextual_question
from initiation.memory_interface import mark_answered, store_fact

# ── Load Config ───────────────────────────────────────────────────

_CONFIG_PATH = config.INITIATION_CONFIG_PATH


def _load_config() -> dict:
    """Load initiation config from JSON. Falls back to defaults on error."""
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[Initiation] Config load error, using defaults: {e}")
        return {}


def _cfg(key: str, default=None):
    """Get a config value with fallback. Supports dotted nested keys."""
    cfg = _load_config()
    parts = key.split(".")
    val = cfg
    for part in parts:
        if isinstance(val, dict):
            val = val.get(part)
        else:
            return default
    return val if val is not None else default


# ── Engine State ──────────────────────────────────────────────────

_state = {
    "last_initiation_time": 0,
    "last_initiation_register": None,
    "daily_counts": {"idle": 0, "contextual": 0, "reflective": 0},
    "daily_counts_date": None,
    "pending_question": None,
    "last_human_spoke": 0,
    "conversation_active": False,
}

_lock = threading.Lock()
_thread = None
_running = False
_speak_fn = None
_emit_transcript_fn = None
_set_state_fn = None
_context = None


# ── Daily Reset ───────────────────────────────────────────────────

def _check_daily_reset():
    today = date.today().isoformat()
    with _lock:
        if _state["daily_counts_date"] != today:
            _state["daily_counts"] = {"idle": 0, "contextual": 0, "reflective": 0}
            _state["daily_counts_date"] = today


# ── Trigger Conditions ────────────────────────────────────────────

def _should_initiate() -> tuple[bool, str]:
    """Check all conditions for initiation. Returns (allowed, reason)."""
    now = time.time()
    tz = ZoneInfo(config.TIMEZONE)
    hour = datetime.now(tz).hour

    # Night silence
    night_start = _cfg("night_start_hour", 1)
    night_end = _cfg("night_end_hour", 6)
    if night_start <= hour < night_end:
        return False, "night_silence"

    # Minimum gap
    min_gap = _cfg("min_gap_minutes", 45) * 60
    with _lock:
        if _state["last_initiation_time"] > 0:
            elapsed = now - _state["last_initiation_time"]
            if elapsed < min_gap:
                return False, f"min_gap ({int((min_gap - elapsed) / 60)}m remaining)"

    # User mid-task
    if _context:
        if getattr(_context, 'user_away', False):
            return False, "user_away"
        if getattr(_context, 'session_mode', 'normal') == 'meditation':
            return False, "meditation"

    # Conversation active
    with _lock:
        if _state["conversation_active"]:
            return False, "conversation_active"

    # Post-interaction cooldown
    cooldown = _cfg("post_interaction_cooldown_minutes", 10) * 60
    with _lock:
        if _state["last_human_spoke"] > 0:
            elapsed = now - _state["last_human_spoke"]
            if elapsed < cooldown:
                return False, "post_interaction_cooldown"

    # Lull detection
    lull_threshold = _cfg("lull_silence_minutes", 8) * 60
    with _lock:
        if _state["last_human_spoke"] > 0:
            silence = now - _state["last_human_spoke"]
            if silence < lull_threshold:
                return False, "waiting_for_lull"

    # Already pending
    with _lock:
        if _state["pending_question"] is not None:
            return False, "pending_question"

    return True, "clear"


# ── Register Selection ────────────────────────────────────────────

def _pick_register() -> str | None:
    """Weighted random register selection with adjustments."""
    _check_daily_reset()

    weights = {
        "idle": _cfg("register_weights.idle", 60),
        "contextual": _cfg("register_weights.contextual", 30),
        "reflective": _cfg("register_weights.reflective", 10),
    }

    with _lock:
        last = _state["last_initiation_register"]
    if last == "idle":
        weights["idle"] *= _cfg("repeat_penalty_idle", 0.4)
    elif last == "contextual":
        weights["contextual"] *= _cfg("repeat_penalty_contextual", 0.5)
    elif last == "reflective":
        weights["reflective"] *= 0.3

    heavy_recently = _detect_heavy_conversation()
    if heavy_recently:
        weights["idle"] *= _cfg("heavy_conversation_idle_boost", 1.5)
        weights["reflective"] *= _cfg("heavy_conversation_reflective_dampen", 0.3)

    tz = ZoneInfo(config.TIMEZONE)
    hour = datetime.now(tz).hour
    quiet_start = _cfg("quiet_window_start_hour", 20)
    quiet_end = _cfg("quiet_window_end_hour", 23)
    if not (quiet_start <= hour < quiet_end):
        weights["reflective"] = 0

    caps = {
        "idle": _cfg("daily_caps.idle", 4),
        "contextual": _cfg("daily_caps.contextual", 2),
        "reflective": _cfg("daily_caps.reflective", 1),
    }
    with _lock:
        for reg, cap in caps.items():
            if _state["daily_counts"].get(reg, 0) >= cap:
                weights[reg] = 0

    total = sum(weights.values())
    if total == 0:
        return None

    r = random.uniform(0, total)
    cumulative = 0
    for reg, w in weights.items():
        cumulative += w
        if r <= cumulative:
            return reg

    return "idle"


def _detect_heavy_conversation() -> bool:
    """Detect if there was a heavy/long conversation recently."""
    if not _context:
        return False
    try:
        transcript = getattr(_context, 'recent_transcript', '')
        return len(transcript) > 2000
    except Exception:
        return False


# ── Question Selection ────────────────────────────────────────────

def _pick_question(register: str) -> dict | None:
    """Select a question for the given register."""
    if register == "idle":
        return pick_idle_question()
    elif register == "contextual":
        cooldown = _cfg("anchor_cooldown_days", 14)
        return pick_contextual_question(cooldown_days=cooldown)
    elif register == "reflective":
        return pick_reflective_question()
    return None


# ── Speech Delivery ───────────────────────────────────────────────

def _deliver(question: dict, register: str):
    """Deliver the question through Nova's voice pipeline."""
    if not _speak_fn or not _emit_transcript_fn:
        print(f"[Initiation] Speech not wired. Question: {question['text']}")
        return

    text = question["text"]
    print(f"[Initiation | {register}] {text}")

    # ── Speech-gate check ──
    try:
        from pipeline.speech_gate import speech_gate
        payload = {
            "text": text,
            "register": register,
            "id": question.get("id"),
        }
        ctx = {
            "session_mode": getattr(_context, "session_mode", "normal") if _context else "normal",
            "user_away": bool(getattr(_context, "user_away", False)) if _context else False,
            "conversation_active": _state.get("conversation_active", False),
        }
        allowed = speech_gate.should_speak("initiation_engine", payload, ctx)
    except Exception as _e:
        print(f"[Initiation] Speech gate error (suppressing): {_e}")
        allowed = False

    if not allowed:
        return

    if _set_state_fn:
        _set_state_fn("speaking")

    _emit_transcript_fn("nova", text)
    _speak_fn(text)

    if _context:
        try:
            _context.add_nova_utterance(text)
        except Exception:
            pass

    print(f"[Initiation] Delivered: [{register}] {text[:80]}...")


# ── Answer Processing ─────────────────────────────────────────────

PENDING_EXPIRY_SECONDS = 10 * 60


def has_pending_question() -> bool:
    """Check if the engine has a non-expired question awaiting an answer."""
    with _lock:
        q = _state["pending_question"]
        if q is None:
            return False
        asked_at = q.get("_asked_at", 0)
        if time.time() - asked_at > PENDING_EXPIRY_SECONDS:
            _state["pending_question"] = None
            return False
        return True


def get_pending_question() -> dict | None:
    """Return the pending question, if any."""
    with _lock:
        return _state["pending_question"]


def process_answer(user_input: str):
    """
    Called when the user responds to an initiation question.
    Stores the answer and extracts a fact anchor.
    """
    with _lock:
        question = _state["pending_question"]
        if question is None:
            return
        _state["pending_question"] = None

    question_id = question["id"]
    register = question.get("_register", "idle")

    mark_answered(question_id, user_input, register)

    anchor_key = question_id.replace("contextual_", "")
    store_fact(anchor_key, user_input, source_question_id=question_id)

    print(f"[Initiation] Answer stored for {question_id}: {user_input[:60]}...")


# ── Main Loop ─────────────────────────────────────────────────────

def _loop():
    """Background loop. Checks conditions periodically; fires when appropriate."""
    time.sleep(60)

    while _running:
        try:
            can, reason = _should_initiate()
            if not can:
                if "min_gap" in reason:
                    time.sleep(60)
                elif reason == "waiting_for_lull":
                    time.sleep(30)
                else:
                    time.sleep(30)
                continue

            register = _pick_register()
            if register is None:
                time.sleep(300)
                continue

            question = _pick_question(register)
            if question is None:
                print(f"[Initiation] No question available for register '{register}'")
                time.sleep(120)
                continue

            question["_register"] = register
            question["_asked_at"] = time.time()

            with _lock:
                _state["pending_question"] = question
                _state["last_initiation_time"] = time.time()
                _state["last_initiation_register"] = register
                _state["daily_counts"][register] = _state["daily_counts"].get(register, 0) + 1

            _deliver(question, register)

            min_gap = _cfg("min_gap_minutes", 45) * 60
            time.sleep(min_gap)

        except Exception as e:
            print(f"[Initiation] Loop error: {e}")
            time.sleep(60)


# ── External Notifications ────────────────────────────────────────

def notify_human_spoke():
    """Called when the user speaks — updates lull and conversation state."""
    with _lock:
        _state["last_human_spoke"] = time.time()
        _state["conversation_active"] = True


def notify_conversation_ended():
    """Called when the conversation appears to have ended."""
    with _lock:
        _state["conversation_active"] = False


def notify_nova_spoke():
    """Called when Nova speaks through any system — resets timing."""
    with _lock:
        _state["last_initiation_time"] = time.time()


# ── Lifecycle ─────────────────────────────────────────────────────

def start(speak_fn, emit_transcript_fn, set_state_fn, context=None):
    """Start the initiation engine."""
    global _thread, _running, _speak_fn, _emit_transcript_fn, _set_state_fn, _context

    _speak_fn = speak_fn
    _emit_transcript_fn = emit_transcript_fn
    _set_state_fn = set_state_fn
    _context = context
    _running = True

    _thread = threading.Thread(target=_loop, daemon=True)
    _thread.start()

    cfg = _load_config()
    caps = cfg.get("daily_caps", {})
    print(f"[Initiation] Engine started — "
          f"{_cfg('min_gap_minutes', 45)}m gap, "
          f"caps: idle={caps.get('idle', 4)}, "
          f"contextual={caps.get('contextual', 2)}, "
          f"reflective={caps.get('reflective', 1)}")


def stop():
    """Stop the initiation engine."""
    global _running
    _running = False
    print("[Initiation] Engine stopped")


def get_state() -> dict:
    """Return a copy of the engine state for diagnostics."""
    with _lock:
        return dict(_state)
