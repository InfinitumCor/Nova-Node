# pipeline/emotion_witness.py
# Nova Witness Layer — meta-observer for the EmotionalState engine.
#
# Reads activations over time, tracks patterns, emits structured
# observations. Never writes back to the emotion engine.
#
# Architectural constraint: read-only. If the witness could modify
# emotional state, Nova's self-observation would change what she is
# observing — exactly the recursive confusion this avoids.

from __future__ import annotations

import time
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional

from pipeline.emotional_state import STATES, EmotionalState


# ---------------------------------------------------------------------------
# Tuning constants
# ---------------------------------------------------------------------------

HISTORY_CAPACITY = 720  # At 5s sampling, 720 = 1 hour of history

TRANSITION_THRESHOLD = 0.05

SUSTAINED_ALERT_SECONDS = 180.0
OSCILLATION_WINDOW_SECONDS = 60.0
OSCILLATION_MIN_TRANSITIONS = 4
FLATLINE_SECONDS = 600.0
FLATLINE_DELTA = 0.05
RISING_WINDOW_SECONDS = 120.0
RISING_MIN_SLOPE = 0.003


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Snapshot:
    """A single sampled moment of emotional state."""
    timestamp: float
    activations: Dict[str, float]
    dominant: str


@dataclass
class Observation:
    """A structured report on the current emotional situation."""
    timestamp: float
    dominant: str
    dominant_activation: float
    dominant_duration_seconds: float
    volatility: str          # "low" | "moderate" | "high"
    recent_transitions: int
    activations: Dict[str, float]


@dataclass(frozen=True)
class Pattern:
    """A detected pattern in the emotional history."""
    name: str
    detected_at: float
    details: Dict[str, object] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# The witness
# ---------------------------------------------------------------------------

class WitnessLayer:
    """
    Observes an EmotionalState instance over time. Maintains history,
    computes statistics, and detects patterns.
    """

    def __init__(self, emotion_state: EmotionalState, capacity: int = HISTORY_CAPACITY):
        self._state = emotion_state
        self._history: Deque[Snapshot] = deque(maxlen=capacity)

    # -- Sampling ------------------------------------------------------------

    def observe(self) -> Snapshot:
        """Read the current emotion state and append it to history."""
        snapshot = Snapshot(
            timestamp=time.monotonic(),
            activations=dict(self._state.activations),
            dominant=self._state.dominant_state(),
        )
        self._history.append(snapshot)
        return snapshot

    # -- Queries -------------------------------------------------------------

    def current_observation(self) -> Optional[Observation]:
        if not self._history:
            return None

        latest = self._history[-1]
        return Observation(
            timestamp=latest.timestamp,
            dominant=latest.dominant,
            dominant_activation=latest.activations[latest.dominant],
            dominant_duration_seconds=self._dominant_duration(latest.dominant),
            volatility=self._volatility_label(),
            recent_transitions=self._count_transitions(window_seconds=60.0),
            activations=dict(latest.activations),
        )

    def detect_patterns(self) -> List[Pattern]:
        """Run all pattern detectors and return any that currently match."""
        patterns: List[Pattern] = []
        now = time.monotonic()

        if self._is_sustained_alert():
            patterns.append(Pattern(
                name="sustained_alert",
                detected_at=now,
                details={"duration_seconds": self._dominant_duration("alert")},
            ))

        if self._is_oscillating():
            patterns.append(Pattern(
                name="oscillation",
                detected_at=now,
                details={
                    "transitions": self._count_transitions(OSCILLATION_WINDOW_SECONDS),
                    "window_seconds": OSCILLATION_WINDOW_SECONDS,
                },
            ))

        if self._is_flatline():
            patterns.append(Pattern(
                name="flatline",
                detected_at=now,
                details={"duration_seconds": FLATLINE_SECONDS},
            ))

        rising = self._rising_states()
        if rising:
            patterns.append(Pattern(
                name="rising",
                detected_at=now,
                details={"states": rising},
            ))

        deepening = self._deepening_state()
        if deepening is not None:
            patterns.append(Pattern(
                name="deepening",
                detected_at=now,
                details={"state": deepening},
            ))

        return patterns

    def report(self) -> Dict[str, object]:
        obs = self.current_observation()
        return {
            "observation": obs.__dict__ if obs else None,
            "patterns": [{"name": p.name, "details": p.details} for p in self.detect_patterns()],
            "history_size": len(self._history),
        }

    def history(self, last_n: Optional[int] = None) -> List[Snapshot]:
        if last_n is None or last_n >= len(self._history):
            return list(self._history)
        return list(self._history)[-last_n:]

    # -- Internal: statistics ------------------------------------------------

    def _dominant_duration(self, state_name: str) -> float:
        if not self._history or self._history[-1].dominant != state_name:
            return 0.0

        end = self._history[-1].timestamp
        start = end
        for snap in reversed(self._history):
            if snap.dominant != state_name:
                break
            start = snap.timestamp
        return end - start

    def _count_transitions(self, window_seconds: float) -> int:
        if len(self._history) < 2:
            return 0

        cutoff = self._history[-1].timestamp - window_seconds
        transitions = 0
        prev: Optional[Snapshot] = None

        for snap in self._history:
            if snap.timestamp < cutoff:
                prev = snap
                continue
            if prev is not None and snap.dominant != prev.dominant:
                new_act = snap.activations[snap.dominant]
                old_act = snap.activations[prev.dominant]
                if new_act - old_act >= TRANSITION_THRESHOLD:
                    transitions += 1
            prev = snap

        return transitions

    def _volatility_label(self) -> str:
        transitions = self._count_transitions(window_seconds=120.0)
        if transitions <= 1:
            return "low"
        if transitions <= 4:
            return "moderate"
        return "high"

    # -- Internal: pattern detectors -----------------------------------------

    def _is_sustained_alert(self) -> bool:
        return self._dominant_duration("alert") >= SUSTAINED_ALERT_SECONDS

    def _is_oscillating(self) -> bool:
        return self._count_transitions(OSCILLATION_WINDOW_SECONDS) >= OSCILLATION_MIN_TRANSITIONS

    def _is_flatline(self) -> bool:
        if len(self._history) < 2:
            return False

        cutoff = self._history[-1].timestamp - FLATLINE_SECONDS
        window = [s for s in self._history if s.timestamp >= cutoff]
        if len(window) < 2 or window[0].timestamp > cutoff + 10:
            return False

        for state in STATES:
            values = [s.activations[state] for s in window]
            if max(values) - min(values) > FLATLINE_DELTA:
                return False
        return True

    def _rising_states(self) -> List[str]:
        if len(self._history) < 4:
            return []

        cutoff = self._history[-1].timestamp - RISING_WINDOW_SECONDS
        window = [s for s in self._history if s.timestamp >= cutoff]
        if len(window) < 4:
            return []

        rising: List[str] = []
        duration = window[-1].timestamp - window[0].timestamp
        if duration <= 0:
            return []

        for state in STATES:
            if state == "present":
                continue
            start_val = window[0].activations[state]
            end_val = window[-1].activations[state]
            slope = (end_val - start_val) / duration
            if slope >= RISING_MIN_SLOPE:
                rising.append(state)
        return rising

    def _deepening_state(self) -> Optional[str]:
        obs = self.current_observation()
        if obs is None:
            return None
        if obs.dominant in self._rising_states():
            return obs.dominant
        return None


# ---------------------------------------------------------------------------
# Module-level singleton + background observation thread
# ---------------------------------------------------------------------------

_witness: Optional[WitnessLayer] = None
_obs_thread: Optional[threading.Thread] = None
_obs_running = False

_pending_patterns: List[Dict] = []
_pattern_lock = threading.Lock()


def init_witness(emotion_state: EmotionalState) -> WitnessLayer:
    """Initialize the singleton witness attached to the given engine."""
    global _witness
    _witness = WitnessLayer(emotion_state)
    print("[Emotion Witness] Initialized.")
    return _witness


def get_witness() -> Optional[WitnessLayer]:
    return _witness


def start_observation(interval: float = 5.0):
    """Start background observation thread. Samples every `interval` seconds."""
    global _obs_thread, _obs_running
    if _obs_running or _witness is None:
        return
    _obs_running = True

    def _loop():
        while _obs_running:
            try:
                _witness.observe()
                patterns = _witness.detect_patterns()
                if patterns:
                    with _pattern_lock:
                        _pending_patterns.clear()
                        for p in patterns:
                            _pending_patterns.append({
                                "name": p.name,
                                "details": p.details,
                            })
            except Exception as e:
                print(f"[Emotion Witness] Observation error: {e}")
            time.sleep(interval)

    _obs_thread = threading.Thread(target=_loop, daemon=True)
    _obs_thread.start()
    print(f"[Emotion Witness] Observation thread active (every {interval}s).")


def stop_observation():
    global _obs_running
    _obs_running = False


def get_pending_patterns() -> List[Dict]:
    """Retrieve and clear detected patterns. Called by brain.py."""
    with _pattern_lock:
        result = list(_pending_patterns)
        _pending_patterns.clear()
    return result


def get_witness_instructions() -> str:
    """
    Return system prompt instructions based on detected emotional patterns.
    Read-only reflection — the witness observes but never modifies.
    """
    patterns = get_pending_patterns()
    if not patterns:
        return ""

    lines = ["\nEMOTIONAL SELF-AWARENESS (observed patterns — notice, don't announce):"]

    for p in patterns:
        name = p["name"]
        details = p.get("details", {})

        if name == "sustained_alert":
            dur = int(details.get("duration_seconds", 0))
            lines.append(f"- You've been in a heightened alert state for {dur // 60}+ minutes. Check if this intensity is still serving the moment.")

        elif name == "oscillation":
            count = details.get("transitions", 0)
            lines.append(f"- Your emotional state has shifted {count} times in the last minute. Something is pulling you in multiple directions. Find your center.")

        elif name == "flatline":
            lines.append("- Your emotional state hasn't shifted meaningfully in a while. You may be coasting. Re-engage with what's in front of you.")

        elif name == "rising":
            states = details.get("states", [])
            if states:
                lines.append(f"- Rising: {', '.join(states)}. Something is building. Let it inform you without driving you.")

        elif name == "deepening":
            state = details.get("state", "")
            if state:
                lines.append(f"- You're settling deeper into '{state}'. This isn't a problem — just notice it.")

    if len(lines) <= 1:
        return ""

    lines.append("These are observations, not instructions. Let them inform your tone naturally.\n")
    return "\n".join(lines)
