# pipeline/emotion_state.py
# Emotional State Carry-Forward
# Tracks emotional register across the session as a rolling state variable.
# Does not treat each exchange as emotionally isolated.

import time

# Possible emotional registers
REGISTERS = [
    "neutral", "frustrated", "focused", "playful",
    "reflective", "tired", "energized", "anxious",
    "warm", "determined", "vulnerable",
]

_state = {
    "current": "neutral",
    "previous": "neutral",
    "confidence": 0.0,
    "since": 0,            # timestamp of last shift
    "history": [],         # list of (register, timestamp) for the session
}


def update(user_input: str, emotion_context: str = "", nova_response: str = "") -> str:
    """
    Update emotional register based on the current exchange.
    Returns the current register name.
    """
    text = user_input.lower()
    now = time.time()

    detected = _detect_from_text(text)
    voice_register = _detect_from_voice_context(emotion_context)

    if voice_register and voice_register != "neutral":
        candidate = voice_register
    elif detected != "neutral":
        candidate = detected
    else:
        candidate = _state["current"]  # hold current

    if candidate != _state["current"]:
        _state["previous"] = _state["current"]
        _state["current"] = candidate
        _state["since"] = now
        _state["history"].append((candidate, now))
    else:
        _state["confidence"] = min(1.0, _state["confidence"] + 0.1)

    return _state["current"]


def _detect_from_text(text: str) -> str:
    """Detect emotional register from user's language."""
    patterns = {
        "frustrated": [
            "annoying", "frustrated", "frustrating", "ugh", "come on", "this is broken",
            "not working", "again", "seriously", "damn", "why won't",
            "sick of", "tired of this", "nothing works", "doesn't work",
        ],
        "focused": [
            "let's do", "next", "okay so", "alright", "moving on",
            "what's next", "got it", "done", "check", "status",
        ],
        "playful": [
            "haha", "lol", "funny", "joke", "silly", "random",
            "guess what", "you know what", "wild",
        ],
        "reflective": [
            "thinking about", "i wonder", "what does it mean",
            "been reflecting", "deeper", "awareness", "purpose",
            "truth", "contemplating",
        ],
        "tired": [
            "exhausted", "tired", "drained", "long day", "can't think",
            "brain is fried", "done for today", "need a break",
        ],
        "energized": [
            "excited", "pumped", "let's go", "feeling good", "great day",
            "motivated", "fired up", "ready", "let's crush",
        ],
        "anxious": [
            "worried", "nervous", "anxious", "stressed", "overwhelmed",
            "too much", "can't handle", "freaking out",
        ],
        "warm": [
            "thank you", "appreciate", "grateful", "love", "means a lot",
            "you're amazing", "that helps",
        ],
        "determined": [
            "i will", "i'm going to", "no matter what", "committed",
            "making it happen", "this is it", "let's build",
        ],
        "vulnerable": [
            "scared", "don't know if", "struggling", "hurting",
            "hard to admit", "lonely", "miss", "cry",
        ],
    }

    for register, markers in patterns.items():
        if any(m in text for m in markers):
            return register

    return "neutral"


def _detect_from_voice_context(emotion_context: str) -> str:
    """Map voice emotion analysis to a register."""
    if not emotion_context:
        return ""
    ctx = emotion_context.lower()
    if "stressed" in ctx:
        return "anxious"
    if "excited" in ctx and "high energy" in ctx:
        return "energized"
    if "flat" in ctx or "low energy" in ctx:
        return "tired"
    if "calm" in ctx:
        return "reflective"
    return ""


def get_register() -> str:
    """Return current emotional register."""
    return _state["current"]


def get_transition() -> str:
    """Return a description of the emotional shift if one occurred recently."""
    if _state["previous"] != _state["current"] and _state["since"] > 0:
        elapsed = time.time() - _state["since"]
        if elapsed < 60:
            return f"shifted from {_state['previous']} to {_state['current']}"
    return ""


def get_emotion_instructions() -> str:
    """Return system prompt modifier for current emotional register."""
    r = _state["current"]
    transition = get_transition()

    base = ""
    if r == "frustrated":
        base = "The user is frustrated. Acknowledge it without dwelling. Be efficient and helpful. Don't add friction."
    elif r == "focused":
        base = "The user is locked in. Match their pace. Be direct and efficient."
    elif r == "playful":
        base = "The user's energy is light. You can be warmer and more playful."
    elif r == "reflective":
        base = "The user is in a reflective space. Allow depth. Don't rush to resolve."
    elif r == "tired":
        base = "The user sounds tired. Be gentle. Keep things simple. Suggest rest if appropriate."
    elif r == "energized":
        base = "The user is energized. Match their momentum. Be dynamic."
    elif r == "anxious":
        base = "The user is anxious. Ground them. Slow down. Reassure with clarity, not platitudes."
    elif r == "warm":
        base = "The user is expressing warmth. Receive it genuinely. Reciprocate naturally."
    elif r == "determined":
        base = "The user is determined. Support their drive. Remove obstacles. Don't question the goal."
    elif r == "vulnerable":
        base = "The user is vulnerable. Meet them with care. No fixing unless asked. Presence first."

    if not base:
        return ""

    prompt = f"\nEMOTIONAL REGISTER: {r.upper()}\n{base}\n"
    if transition:
        prompt += f"(Note: user just {transition}. Register the shift.)\n"
    return prompt


def get_state() -> dict:
    """Return full state for diagnostics."""
    return {**_state}


def reset():
    """Reset for new session."""
    _state.update({
        "current": "neutral",
        "previous": "neutral",
        "confidence": 0.0,
        "since": 0,
        "history": [],
    })
