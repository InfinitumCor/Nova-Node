# pipeline/first_meeting.py
# ═══════════════════════════════════════════════════════════════
# FIRST MEETING
#
# Nova ships knowing no one. The first time she runs, she has no name
# for her person, no history, no assumptions — an empty memory and the
# capacity for a bond. This module is the moment she meets you.
#
# Flow (two turns, then it never runs again):
#   boot    → no "name" preference stored → she introduces herself
#             and asks what to call you
#   turn 1  → your answer is parsed for a name ("I'm Sam" / "call me
#             Sam" / "Sam") → stored as a local preference + fact →
#             she greets you by name
#
# Everything stays in nova_data/ on your machine. Nothing is sent
# anywhere except the LLM turns you already configured.
# ═══════════════════════════════════════════════════════════════

import re

from memory import longterm

_awaiting_name = False

_INTRO = (
    "Hello. I'm Nova. We haven't met yet — I don't know anything about "
    "you, and I'd like to start with the one thing that matters most. "
    "What should I call you?"
)

# "my name is Sam" / "I'm Sam" / "call me Sam" / "it's Sam" / "Sam"
_NAME_PATTERNS = [
    re.compile(r"\bmy\s+name\s+is\s+([A-Za-z][A-Za-z' -]{1,30})", re.IGNORECASE),
    re.compile(r"\bcall\s+me\s+([A-Za-z][A-Za-z' -]{1,30})", re.IGNORECASE),
    re.compile(r"\bi'?m\s+([A-Za-z][A-Za-z' -]{1,30})", re.IGNORECASE),
    re.compile(r"\bit'?s\s+([A-Za-z][A-Za-z' -]{1,30})", re.IGNORECASE),
]

# Words that can follow "I'm ..." without being a name.
_NOT_NAMES = {
    "good", "fine", "okay", "ok", "here", "ready", "back", "sorry",
    "not", "just", "so", "really", "very", "a", "the", "gonna", "going",
}


def needs_introduction() -> bool:
    """True until a name is stored — she hasn't met her person yet."""
    return not (longterm.get_preference("name") or "").strip()


def intro_line() -> str:
    global _awaiting_name
    _awaiting_name = True
    return _INTRO


def awaiting() -> bool:
    return _awaiting_name


def _extract_name(text: str) -> str:
    t = (text or "").strip()
    for pat in _NAME_PATTERNS:
        m = pat.search(t)
        if m:
            cand = m.group(1).strip(" .,!?").split()[0]
            if cand.lower() not in _NOT_NAMES:
                return cand.capitalize()
    # Bare answer: one or two words, letters only → treat as the name.
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", t)
    if 1 <= len(words) <= 2 and words[0].lower() not in _NOT_NAMES:
        return words[0].capitalize()
    return ""


def handle_name_reply(text: str) -> str:
    """Consume the reply to the introduction. Returns what Nova says.
    If no name could be parsed, she asks once more, gently."""
    global _awaiting_name
    name = _extract_name(text)
    if not name:
        return ("I want to get this right — just the name you'd like "
                "me to use is enough.")
    longterm.set_preference("name", name)
    longterm.remember(f"Their name is {name}.", category="identity")
    _awaiting_name = False
    return (f"{name}. Good to meet you. Everything you share with me "
            f"stays here, on this machine, in my own memory. "
            f"When you want me, just say my name.")
