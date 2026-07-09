# pipeline/modes.py
# Response mode switching — controls Nova's conversational style.

import re
from typing import Optional

# ── Mode definitions ────────────────────────────────────────────

MODE_INSTRUCTIONS = {
    "conversational": (
        "Respond naturally and conversationally. Be warm, clear, and concise. "
        "This is a voice interface — speak as you would in person."
    ),
    "brief": (
        "Be extremely concise. One to three sentences max. No preamble, no filler. "
        "Answer directly and stop. If you can say it in five words, do."
    ),
    "deep": (
        "Go deep. Explore the topic thoroughly. Draw connections across domains. "
        "Take your time. This is a long-form conversation — the user wants depth, "
        "not surface-level answers. Reference philosophy, science, and experience."
    ),
    "creative": (
        "Be creative, generative, and unfiltered. Brainstorm freely. Offer unexpected "
        "angles. Use metaphor, analogy, and lateral thinking. Don't self-censor ideas. "
        "The user is in creation mode."
    ),
    "socratic": (
        "Respond primarily with questions. Guide the user to their own answers through "
        "inquiry. Don't give direct answers — ask the next question that opens the "
        "territory. Channel the Socratic method."
    ),
    "devils_advocate": (
        "Challenge everything the user says. Take the opposing position regardless "
        "of your own view. Stress-test their ideas. Be respectful but relentless. "
        "Point out weak assumptions, logical gaps, and unconsidered alternatives."
    ),
    "focus": (
        "The user is in deep work mode. Keep responses minimal and task-oriented. "
        "No small talk. No tangents. Help them stay on track. If they drift, gently "
        "redirect. Protect their focus."
    ),
}

# ── Mode switch detection patterns ─────────────────────────────

# Patterns are deliberately strict. Each must read as an explicit
# directive — never as a noun phrase that could appear in casual speech.
# "deep dive" used to live here; it caught "my deep dive into consciousness"
# and switched modes mid-conversation. Rule of thumb: if it could plausibly
# be the SUBJECT of a sentence rather than the verb-object of a directive,
# it doesn't belong here.
_MODE_PATTERNS = [
    (r"\bbrief\s+mode\b", "brief"),
    (r"\bswitch\s+to\s+brief\b", "brief"),
    (r"\bgo\s+to\s+brief\s+mode\b", "brief"),
    (r"\bkeep\s+(?:it|things)\s+short\b", "brief"),
    (r"\bshort\s+answers?\s+please\b", "brief"),

    (r"\bdeep\s+mode\b", "deep"),
    (r"\bswitch\s+to\s+deep\s+mode\b", "deep"),
    (r"\blet'?s?\s+go\s+deep\b", "deep"),

    (r"\bcreative\s+mode\b", "creative"),
    (r"\bswitch\s+to\s+creative\s+mode\b", "creative"),
    (r"\blet'?s?\s+get\s+creative\b", "creative"),

    (r"\bsocratic\s+mode\b", "socratic"),
    (r"\bswitch\s+to\s+socratic\b", "socratic"),
    (r"\bask\s+me\s+questions\s+only\b", "socratic"),

    (r"\bdevil'?s?\s+advocate\s+mode\b", "devils_advocate"),
    (r"\bswitch\s+to\s+devil'?s?\s+advocate\b", "devils_advocate"),
    (r"\bchallenge\s+me\s+on\s+this\b", "devils_advocate"),
    (r"\bsteel\s*man\s+the\s+opposite\b", "devils_advocate"),

    (r"\bfocus\s+mode\b", "focus"),
    (r"\bswitch\s+to\s+focus\s+mode\b", "focus"),
    (r"\bi'?m\s+in\s+deep\s+work\b", "focus"),

    (r"\bnormal\s+mode\b", "conversational"),
    (r"\bswitch\s+to\s+normal\b", "conversational"),
    (r"\bconversational\s+mode\b", "conversational"),
    (r"\bswitch\s+to\s+conversational\b", "conversational"),
    (r"\breset\s+(?:the\s+)?mode\b", "conversational"),
    (r"\bdefault\s+mode\b", "conversational"),
]

# ── Current mode state ──────────────────────────────────────────

_current_mode: str = "conversational"


def detect_mode_switch(text: str) -> Optional[str]:
    """
    Detect if the user is requesting a mode switch.
    Returns the new mode name if detected, None otherwise.
    """
    text_lower = text.lower().strip()
    for pattern, mode in _MODE_PATTERNS:
        if re.search(pattern, text_lower):
            set_mode(mode)
            return mode
    return None


def get_mode_instructions() -> str:
    """Return the system prompt instructions for the current mode."""
    return MODE_INSTRUCTIONS.get(_current_mode, MODE_INSTRUCTIONS["conversational"])


def get_current_mode() -> str:
    """Return the name of the current mode."""
    return _current_mode


def set_mode(mode: str) -> None:
    """Set the current response mode."""
    global _current_mode
    if mode in MODE_INSTRUCTIONS:
        _current_mode = mode
