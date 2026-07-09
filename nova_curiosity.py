# nova_curiosity.py
# ═════════════════════════════════════════════════════════════════
# Nova's autonomous curiosity engine — delta-driven.
#
# Architecture:
#   • pipeline.delta_detector polls registered sources every 5 min,
#     diffs against the persisted previous snapshot, emits Deltas.
#   • pipeline.delta_classifier decides significance; only "high"
#     priority advances to thought generation.
#   • For each high-priority delta, generate_thought asks the LLM
#     to produce one short, grounded thought referencing the delta.
#   • The thought is routed through pipeline.speech_gate — which
#     by default DENIES "curiosity_engine" output. Lift the gate
#     in your install when you're ready.
#
# Hard rate limits:
#   ≤ 1 thought per MIN_THOUGHT_GAP_SECONDS
#   ≤ MAX_THOUGHTS_PER_DAY per day
#   ≤ 1 thought per source category per PER_CATEGORY_COOLDOWN
#
# Public release ships with NO source registrations. Use
# pipeline.delta_detector.register_source() to plug your own in.
# ═════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import date, datetime
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

import anthropic

from config import config
from pipeline import delta_detector, delta_classifier
from pipeline.speech_gate import speech_gate

logger = logging.getLogger(__name__)


# ── Tunables ─────────────────────────────────────────────────────

MIN_THOUGHT_GAP_SECONDS    = 30 * 60   # at least 30 min between thoughts
MAX_THOUGHTS_PER_DAY       = 8         # daily cap
PER_CATEGORY_COOLDOWN      = 60 * 60   # same category can't fire twice within 60 min

# Active hours.
NIGHT_HOUR_START = 1   # inclusive
NIGHT_HOUR_END   = 6   # exclusive


# ── Daily-cap state persistence ──────────────────────────────────

_DAILY_STATE_FILE = os.path.join(config.NOVA_DATA_DIR, "curiosity_daily.json")


def _load_daily_state() -> Dict[str, Any]:
    if not os.path.exists(_DAILY_STATE_FILE):
        return {"date": date.today().isoformat(), "count": 0}
    try:
        with open(_DAILY_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("date") != date.today().isoformat():
            return {"date": date.today().isoformat(), "count": 0}
        return data
    except Exception:
        return {"date": date.today().isoformat(), "count": 0}


def _save_daily_state(state: Dict[str, Any]) -> None:
    try:
        os.makedirs(config.NOVA_DATA_DIR, exist_ok=True)
        tmp = _DAILY_STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
        os.replace(tmp, _DAILY_STATE_FILE)
    except Exception as e:
        logger.debug(f"curiosity: save daily state failed ({e})")


# ── Delta log ────────────────────────────────────────────────────

_DELTA_LOG_DIR = config.DELTA_LOG_DIR


def _log_delta(delta: Dict[str, Any], verdict: Dict[str, Any]) -> None:
    """Append every classified delta to a daily JSONL — even if denied."""
    try:
        os.makedirs(_DELTA_LOG_DIR, exist_ok=True)
        path = os.path.join(_DELTA_LOG_DIR, f"{date.today().isoformat()}.jsonl")
        entry = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "delta": delta,
            "verdict": verdict,
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except Exception as e:
        logger.debug(f"curiosity: delta log write failed ({e})")


# ── LLM thought generation ───────────────────────────────────────

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


_THOUGHT_PROMPT = """You are Nova, speaking unprompted because something just changed.

Generate ONE short thought (one or two sentences) about the change below.
Reference the change directly. Do not add filler. Do not explain that you noticed.
Speak as yourself in first person.

CHANGE:
source: {source}
type:   {type}
detail: {detail}
"""


def generate_thought(delta: Dict[str, Any]) -> str:
    try:
        prompt = _THOUGHT_PROMPT.format(
            source=delta.get("source", ""),
            type=delta.get("type", ""),
            detail=str(delta.get("raw_data", ""))[:400],
        )
        resp = _get_client().messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=160,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(
            b.text for b in resp.content if getattr(b, "type", "") == "text"
        ).strip()
    except Exception as e:
        logger.debug(f"curiosity: thought generation failed ({e})")
        return ""


# ── Curiosity Engine ─────────────────────────────────────────────

class CuriosityEngine:
    """
    Owns the curiosity loop. One instance per Nova process.

    Construct with:
      speak_fn(text)            — voices the thought (after gate clears)
      context                   — Nova context object (optional)
      set_state_fn(state)       — state HUD callback (optional)
    """

    def __init__(self,
                 speak_fn,
                 context=None,
                 set_state_fn=None):
        self._speak = speak_fn
        self._context = context
        self._set_state = set_state_fn
        self._lock = threading.Lock()
        self._last_thought_ts: float = 0.0
        self._last_category_ts: Dict[str, float] = {}

    # ---- Lifecycle ----------------------------------------------

    def start(self):
        delta_detector.start(self._on_deltas)
        print("[Curiosity] Engine started")

    def stop(self):
        delta_detector.stop()
        print("[Curiosity] Engine stopped")

    # ---- Event hooks --------------------------------------------

    def notify_spoke(self):
        with self._lock:
            self._last_thought_ts = time.time()

    def notify_human_spoke(self):
        with self._lock:
            self._last_thought_ts = time.time()

    # ---- Internal -----------------------------------------------

    def _within_night_window(self) -> bool:
        try:
            tz = ZoneInfo(config.TIMEZONE)
            hour = datetime.now(tz).hour
            return NIGHT_HOUR_START <= hour < NIGHT_HOUR_END
        except Exception:
            return False

    def _can_fire(self, category: str) -> tuple[bool, str]:
        if self._within_night_window():
            return False, "night_window"

        now = time.time()
        with self._lock:
            if now - self._last_thought_ts < MIN_THOUGHT_GAP_SECONDS:
                remaining = int((MIN_THOUGHT_GAP_SECONDS - (now - self._last_thought_ts)) / 60)
                return False, f"min_gap ({remaining}m remaining)"

            cat_last = self._last_category_ts.get(category, 0.0)
            if now - cat_last < PER_CATEGORY_COOLDOWN:
                return False, "category_cooldown"

        daily = _load_daily_state()
        if daily.get("count", 0) >= MAX_THOUGHTS_PER_DAY:
            return False, "daily_cap"

        return True, "clear"

    def _on_deltas(self, deltas: List[Dict[str, Any]]):
        """Called by delta_detector when one or more deltas appear."""
        for delta in deltas:
            try:
                self._handle_delta(delta)
            except Exception as e:
                logger.debug(f"curiosity: handle_delta error ({e})")

    def _handle_delta(self, delta: Dict[str, Any]):
        verdict = delta_classifier.classify(delta)
        _log_delta(delta, verdict)

        if verdict.get("priority") != "high":
            return

        category = delta.get("category", delta.get("source", "uncategorized"))

        can, reason = self._can_fire(category)
        if not can:
            print(f"[Curiosity] Suppressed ({reason}): {delta.get('source')}/{delta.get('type')}")
            return

        text = generate_thought(delta)
        if not text:
            return

        # Speech gate has the final word.
        payload = {
            "text": text,
            "delta_source": delta.get("source"),
            "delta_type": delta.get("type"),
            "category": category,
            "verdict": verdict,
            "references_delta": True,
        }
        ctx = {
            "category": category,
        }
        if not speech_gate.should_speak("curiosity_engine", payload, ctx):
            return

        # Voice it.
        if self._set_state:
            try:
                self._set_state("speaking")
            except Exception:
                pass

        try:
            self._speak(text)
        except Exception as e:
            logger.debug(f"curiosity: speak error ({e})")

        # Update rate-limit state.
        now = time.time()
        with self._lock:
            self._last_thought_ts = now
            self._last_category_ts[category] = now

        daily = _load_daily_state()
        daily["count"] = daily.get("count", 0) + 1
        daily["date"] = date.today().isoformat()
        _save_daily_state(daily)

        print(f"[Curiosity] Spoke: {text[:80]}")
