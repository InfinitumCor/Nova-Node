# pipeline/emotional_state.py
# Nova Emotional State Engine
# A layered emotional model: perception deltas feed six named states
# whose activations blend continuously. The dominant state drives
# sphere color, voice profile, and response modulation.

from __future__ import annotations

import math
import time
import threading
from dataclasses import dataclass, field
from typing import Dict, Tuple


# ---------------------------------------------------------------------------
# State definitions
# ---------------------------------------------------------------------------

STATES = ("present", "warm", "curious", "still", "alert", "dim")

STATE_COLORS: Dict[str, Tuple[int, int, int]] = {
    "present": (235, 235, 240),   # soft white / pale silver
    "warm":    (230, 165,  75),   # amber / honey
    "curious": ( 70, 185, 200),   # teal / cyan
    "still":   ( 55,  65, 130),   # deep indigo
    "alert":   (220, 105,  70),   # soft red-orange
    "dim":     (110, 100, 125),   # muted grey-violet
}

STATE_PROFILES: Dict[str, Dict[str, float]] = {
    "present": {"pace": 1.00, "warmth": 0.50, "variance": 0.30, "directness": 0.60},
    "warm":    {"pace": 0.95, "warmth": 0.90, "variance": 0.40, "directness": 0.50},
    "curious": {"pace": 1.10, "warmth": 0.65, "variance": 0.60, "directness": 0.70},
    "still":   {"pace": 0.80, "warmth": 0.55, "variance": 0.20, "directness": 0.40},
    "alert":   {"pace": 1.15, "warmth": 0.45, "variance": 0.55, "directness": 0.85},
    "dim":     {"pace": 0.85, "warmth": 0.35, "variance": 0.15, "directness": 0.45},
}


# ---------------------------------------------------------------------------
# Tuning constants
# ---------------------------------------------------------------------------

DECAY_HALFLIFE_SECONDS = 90.0
MOMENTUM = 0.25
ACTIVATION_MIN = 0.0
ACTIVATION_MAX = 1.0
PRESENT_FLOOR = 0.15


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------

@dataclass
class EmotionalState:
    """
    Holds the current activation vector and handles updates, decay, and
    queries for color and voice profile.
    """

    activations: Dict[str, float] = field(default_factory=lambda: {
        "present": 1.0,
        "warm":    0.0,
        "curious": 0.0,
        "still":   0.0,
        "alert":   0.0,
        "dim":     0.0,
    })
    last_tick: float = field(default_factory=time.monotonic)

    def update(self, deltas: Dict[str, float]) -> None:
        """Apply perception deltas with momentum, then tick decay."""
        self._apply_decay()

        for state, delta in deltas.items():
            if state not in self.activations:
                continue
            current = self.activations[state]
            target = _clamp(current + delta, ACTIVATION_MIN, ACTIVATION_MAX)
            self.activations[state] = current + (target - current) * MOMENTUM

        self._enforce_present_floor()

    def tick(self) -> None:
        """Apply decay without new input."""
        self._apply_decay()
        self._enforce_present_floor()

    def _apply_decay(self) -> None:
        now = time.monotonic()
        elapsed = now - self.last_tick
        self.last_tick = now

        if elapsed <= 0:
            return

        decay_factor = math.pow(0.5, elapsed / DECAY_HALFLIFE_SECONDS)

        for state in STATES:
            if state == "present":
                gap = 1.0 - self.activations[state]
                self.activations[state] = 1.0 - gap * decay_factor
            else:
                self.activations[state] *= decay_factor

    def _enforce_present_floor(self) -> None:
        if self.activations["present"] < PRESENT_FLOOR:
            self.activations["present"] = PRESENT_FLOOR

    # -- Query path ----------------------------------------------------------

    def dominant_state(self) -> str:
        return max(self.activations, key=self.activations.get)

    def current_color(self) -> Tuple[int, int, int]:
        total = sum(self.activations.values())
        if total <= 0:
            return STATE_COLORS["present"]

        r = g = b = 0.0
        for state, activation in self.activations.items():
            weight = activation / total
            sr, sg, sb = STATE_COLORS[state]
            r += sr * weight
            g += sg * weight
            b += sb * weight

        return (int(round(r)), int(round(g)), int(round(b)))

    def current_profile(self) -> Dict[str, float]:
        total = sum(self.activations.values())
        if total <= 0:
            return dict(STATE_PROFILES["present"])

        blended: Dict[str, float] = {"pace": 0.0, "warmth": 0.0, "variance": 0.0, "directness": 0.0}
        for state, activation in self.activations.items():
            weight = activation / total
            for key, value in STATE_PROFILES[state].items():
                blended[key] += value * weight

        return blended

    def snapshot(self) -> Dict[str, object]:
        return {
            "activations": dict(self.activations),
            "dominant": self.dominant_state(),
            "color_rgb": self.current_color(),
            "profile": self.current_profile(),
        }


# ---------------------------------------------------------------------------
# Signal mapping layer
# ---------------------------------------------------------------------------

class SignalMapper:
    """Translates perception inputs into state deltas."""

    def from_user_tone(self, tone: str) -> Dict[str, float]:
        return {
            "soft":    {"warm":  0.35, "still":   0.15},
            "harsh":   {"alert": 0.30, "warm":   -0.20},
            "excited": {"curious": 0.30, "warm":  0.15},
            "flat":    {"still": 0.15, "dim":    0.10},
        }.get(tone, {})

    def from_user_silence(self, seconds: float) -> Dict[str, float]:
        if seconds < 5:
            return {}
        if seconds < 30:
            return {"still": 0.15}
        return {"still": 0.10, "dim": 0.15}

    def from_user_novelty(self, novelty: float) -> Dict[str, float]:
        return {"curious": 0.4 * novelty}

    def from_user_distress(self, distress: float) -> Dict[str, float]:
        return {"alert": 0.5 * distress, "warm": 0.3 * distress}

    def from_ignored_duration(self, seconds: float) -> Dict[str, float]:
        if seconds < 60:
            return {}
        if seconds < 300:
            return {"dim": 0.10}
        return {"dim": 0.25, "warm": -0.10}

    def from_voice_emotion(self, energy: str, tone: str, speech_rate: str) -> Dict[str, float]:
        """Map voice emotion analysis into state deltas."""
        deltas: Dict[str, float] = {}

        if energy == "high":
            deltas["alert"] = deltas.get("alert", 0) + 0.15
            deltas["curious"] = deltas.get("curious", 0) + 0.10
        elif energy == "low":
            deltas["still"] = deltas.get("still", 0) + 0.15
            deltas["dim"] = deltas.get("dim", 0) + 0.10

        if tone == "stressed":
            deltas["alert"] = deltas.get("alert", 0) + 0.30
            deltas["warm"] = deltas.get("warm", 0) + 0.15
        elif tone == "excited":
            deltas["curious"] = deltas.get("curious", 0) + 0.25
            deltas["warm"] = deltas.get("warm", 0) + 0.15
        elif tone == "calm":
            deltas["warm"] = deltas.get("warm", 0) + 0.15
            deltas["present"] = deltas.get("present", 0) + 0.10
        elif tone == "flat":
            deltas["dim"] = deltas.get("dim", 0) + 0.20
            deltas["still"] = deltas.get("still", 0) + 0.10

        if speech_rate == "fast":
            deltas["alert"] = deltas.get("alert", 0) + 0.10
            deltas["curious"] = deltas.get("curious", 0) + 0.10
        elif speech_rate == "slow":
            deltas["still"] = deltas.get("still", 0) + 0.15

        return deltas

    def from_emotion_register(self, register: str) -> Dict[str, float]:
        """Map the text-based register from emotion_state.py into state deltas."""
        return {
            "neutral":     {},
            "frustrated":  {"alert": 0.35, "warm": -0.10},
            "focused":     {"present": 0.20, "curious": 0.15},
            "playful":     {"warm": 0.30, "curious": 0.20},
            "reflective":  {"still": 0.30, "warm": 0.10},
            "tired":       {"dim": 0.30, "still": 0.15},
            "energized":   {"curious": 0.25, "warm": 0.20, "alert": 0.10},
            "anxious":     {"alert": 0.35, "warm": 0.20},
            "warm":        {"warm": 0.40, "present": 0.10},
            "determined":  {"alert": 0.15, "curious": 0.20, "present": 0.15},
            "vulnerable":  {"warm": 0.35, "still": 0.20, "alert": 0.10},
        }.get(register, {})


# ---------------------------------------------------------------------------
# Module-level singleton + background decay thread
# ---------------------------------------------------------------------------

_engine: EmotionalState = EmotionalState()
_mapper: SignalMapper = SignalMapper()
_decay_thread: threading.Thread | None = None
_decay_running = False


def get_engine() -> EmotionalState:
    return _engine


def get_mapper() -> SignalMapper:
    return _mapper


def start_decay_thread(interval: float = 3.0):
    """Start a background thread that ticks decay every `interval` seconds."""
    global _decay_thread, _decay_running
    if _decay_running:
        return
    _decay_running = True

    def _loop():
        while _decay_running:
            _engine.tick()
            time.sleep(interval)

    _decay_thread = threading.Thread(target=_loop, daemon=True)
    _decay_thread.start()
    print("[Emotion Engine] Decay thread active.")


def stop_decay_thread():
    global _decay_running
    _decay_running = False


def get_emotion_profile_instructions() -> str:
    """
    Return system prompt instructions based on the current emotional blend.
    Injected alongside the existing emotion_state instructions.
    """
    profile = _engine.current_profile()
    dominant = _engine.dominant_state()

    if dominant == "present" and profile["warmth"] < 0.55:
        return ""

    lines = [f"\nEMOTIONAL TONE: {dominant.upper()}"]

    if profile["warmth"] > 0.70:
        lines.append("Speak with genuine warmth. Let care come through naturally.")
    elif profile["warmth"] < 0.40:
        lines.append("Keep tone measured and composed. Less warmth, more clarity.")

    if profile["pace"] > 1.08:
        lines.append("Your energy is up. Slightly quicker pace, more dynamic.")
    elif profile["pace"] < 0.85:
        lines.append("Slow down. Leave space. Let silence do some of the work.")

    if profile["directness"] > 0.75:
        lines.append("Be direct and clear. Cut to what matters.")
    elif profile["directness"] < 0.45:
        lines.append("Be gentle in delivery. Softer edges.")

    if profile["variance"] > 0.50:
        lines.append("Allow more expressive range in your language.")
    elif profile["variance"] < 0.20:
        lines.append("Stay steady and even. Minimal tonal shifts.")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
