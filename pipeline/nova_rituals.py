"""
nova_rituals.py
---------------
Coordinates Nova's two ritual states:

  1. SILENCE MODE   — shared presence, no response generation
  2. DEEP LISTENING — she holds space, no auto-response

Both states suspend the normal response pipeline. Silence fully
suspends (she won't respond until exit). Listening suspends auto-response
but allows soft replies to direct questions.

Voice invocations handled via phrase matching on transcription output.
"""

import json
import re
import time
from dataclasses import dataclass
from typing import Optional, Callable, Any
from enum import Enum


# =============================================================================
# Ritual state
# =============================================================================

class RitualMode(Enum):
    NORMAL = "normal"
    SILENCE = "silence"
    DEEP_LISTENING = "listening"


@dataclass
class RitualState:
    """Tracks which ritual state Nova is in and coordinates transitions."""
    mode: RitualMode = RitualMode.NORMAL
    entered_at: float = 0.0
    websocket: Any = None

    def is_normal(self) -> bool:
        return self.mode == RitualMode.NORMAL

    def is_silence(self) -> bool:
        return self.mode == RitualMode.SILENCE

    def is_listening(self) -> bool:
        return self.mode == RitualMode.DEEP_LISTENING

    def duration(self) -> float:
        if self.mode == RitualMode.NORMAL:
            return 0.0
        return time.time() - self.entered_at


# Shared state instance — import and use across the codebase
ritual_state = RitualState()


# =============================================================================
# Voice phrase detection
# =============================================================================

SILENCE_ENTRY_PHRASES = [
    r"\bsit with me\b",
    r"\bsilence\b(?!\s+(?:and|but|please))",
    r"\bbe quiet with me\b",
    r"\bjust sit\b",
    r"\bpresence only\b",
]

DEEP_LISTENING_ENTRY_PHRASES = [
    r"\blisten\b(?:\s+to\s+(?:me|this))?$",
    r"\bhold space\b",
    r"\bjust listen\b",
    r"\bwitness this\b",
]

DEEP_LISTENING_EXIT_PHRASES = [
    r"\bthank you\b",
    r"\bthanks nova\b",
    r"\bokay\b(?:,?\s*nova)?$",
]


def matches_any(text: str, patterns: list) -> bool:
    """Case-insensitive match against a list of regex patterns."""
    text_lower = text.lower().strip()
    return any(re.search(p, text_lower) for p in patterns)


def is_silence_invocation(text: str) -> bool:
    return matches_any(text, SILENCE_ENTRY_PHRASES)


def is_listening_invocation(text: str) -> bool:
    return matches_any(text, DEEP_LISTENING_ENTRY_PHRASES)


def is_listening_exit(text: str) -> bool:
    return matches_any(text, DEEP_LISTENING_EXIT_PHRASES)


# =============================================================================
# State transitions
# =============================================================================

async def enter_silence(websocket=None):
    """Enter silence mode. Suspends all response generation."""
    if ritual_state.is_silence():
        return

    ritual_state.mode = RitualMode.SILENCE
    ritual_state.entered_at = time.time()
    ritual_state.websocket = websocket

    if websocket is not None:
        try:
            await websocket.send(json.dumps({"type": "nova.ritual.enter_silence"}))
        except Exception:
            pass


async def exit_silence(websocket=None):
    """Exit silence mode. Normal pipeline resumes."""
    if not ritual_state.is_silence():
        return

    duration = ritual_state.duration()
    ritual_state.mode = RitualMode.NORMAL

    if websocket is not None:
        try:
            await websocket.send(json.dumps({
                "type": "nova.ritual.exit_silence",
                "duration_seconds": duration,
            }))
        except Exception:
            pass


async def enter_deep_listening(websocket=None):
    """Enter deep listening. Auto-response suspended; soft reply still possible."""
    if ritual_state.is_listening():
        return

    ritual_state.mode = RitualMode.DEEP_LISTENING
    ritual_state.entered_at = time.time()
    ritual_state.websocket = websocket

    if websocket is not None:
        try:
            await websocket.send(json.dumps({"type": "nova.ritual.enter_listening"}))
        except Exception:
            pass


async def exit_deep_listening(websocket=None, offer_reflection: bool = False):
    """Exit deep listening. If offer_reflection is True, Nova may softly
    acknowledge what was heard."""
    if not ritual_state.is_listening():
        return

    duration = ritual_state.duration()
    ritual_state.mode = RitualMode.NORMAL

    if websocket is not None:
        try:
            await websocket.send(json.dumps({
                "type": "nova.ritual.exit_listening",
                "duration_seconds": duration,
                "offer_reflection": offer_reflection,
            }))
        except Exception:
            pass


# =============================================================================
# Response pipeline integration
# =============================================================================

def should_suspend_response() -> bool:
    """If True, skip response generation and TTS entirely."""
    return ritual_state.is_silence()


def should_soft_respond() -> bool:
    """Whether a user utterance warrants a soft reply during deep listening."""
    return ritual_state.is_listening()


def is_direct_question(text: str) -> bool:
    """Heuristic: does this utterance need a reply even during deep listening?"""
    text = text.strip().lower()

    if "nova" in text and "?" in text:
        return True
    if re.search(r"^(what|how|why|when|where|who|can you|could you|do you)\b", text):
        return "?" in text or text.startswith(("nova", "hey nova"))

    return False


# =============================================================================
# Main input handler — wraps the existing transcription pipeline
# =============================================================================

async def handle_transcription(
    text: str,
    websocket,
    normal_turn_handler: Callable,
    soft_reply_handler: Optional[Callable] = None,
):
    """
    Route a transcribed user utterance based on current ritual state.

    Call this INSTEAD of going directly to the LLM pipeline.
    """
    text_stripped = text.strip()
    if not text_stripped:
        return

    # --- Silence mode ---
    if ritual_state.is_silence():
        await exit_silence(websocket)
        return

    # --- Deep listening mode ---
    if ritual_state.is_listening():
        if is_listening_exit(text_stripped):
            await exit_deep_listening(websocket, offer_reflection=False)
            return

        if is_direct_question(text_stripped) and soft_reply_handler:
            await soft_reply_handler(text_stripped)
            return

        # Hold space — no response
        return

    # --- Normal mode: check for ritual invocations ---
    if is_silence_invocation(text_stripped):
        await enter_silence(websocket)
        return

    if is_listening_invocation(text_stripped):
        await enter_deep_listening(websocket)
        return

    # --- Normal turn ---
    await normal_turn_handler(text_stripped)


# =============================================================================
# Soft reply directive
# =============================================================================

SOFT_REPLY_DIRECTIVE = """
You are in a deep listening state. The user is processing something and
has asked you a direct question. Respond briefly — one or two sentences
maximum. Stay present and gentle. Do not offer advice unless directly
asked. Do not pivot to other topics. After answering, you will return
to silent listening.
"""
