# pipeline/register.py
# Register Matching — detects the user's current conversational register
# and adjusts response style accordingly.
# Three registers: operational, reflective, creative.
# Toggleable via config.REGISTER_MATCHING_ENABLED.

_current_register = "operational"
_register_momentum = 0  # how many consecutive turns in current register


# Language pattern indicators for each register
OPERATIONAL_SIGNALS = [
    "schedule", "remind", "add", "create", "send", "check", "what time",
    "how much", "when is", "cancel", "delete", "set up", "turn on",
    "turn off", "play", "pause", "skip", "open", "search", "find",
    "do i have", "what's next", "to-do", "task", "agenda", "meeting",
    "email", "call", "order", "buy", "price", "cost", "deadline",
    "how many", "list", "status", "update", "fix", "move", "change",
]

REFLECTIVE_SIGNALS = [
    "what do you think", "how do you feel", "meaning", "purpose",
    "why do", "deeper", "reflect", "awareness", "consciousness",
    "meditation", "philosophy", "insight", "pattern",
    "dream", "journey", "growth",
    "stillness", "presence", "truth",
    "emotion", "feeling", "grateful", "afraid", "wonder",
    "what matters", "what's real", "who am i", "contemplat",
]

CREATIVE_SIGNALS = [
    "write", "draft", "idea", "brainstorm", "imagine", "what if",
    "story", "concept", "design", "build", "create something",
    "poem", "song", "name", "title", "pitch", "brand", "vision",
    "riff on", "play with", "explore the idea", "sketch",
    "content", "post", "thread", "book", "chapter", "outline",
    "experiment", "try something", "creative", "art",
]


def detect_register(user_input: str, emotion_register: str = "") -> str:
    """
    Classify the user's current conversational register.
    Returns: 'operational', 'reflective', or 'creative'
    """
    global _current_register, _register_momentum

    text = user_input.lower()
    scores = {"operational": 0, "reflective": 0, "creative": 0}

    for signal in OPERATIONAL_SIGNALS:
        if signal in text:
            scores["operational"] += 1

    for signal in REFLECTIVE_SIGNALS:
        if signal in text:
            scores["reflective"] += 1

    for signal in CREATIVE_SIGNALS:
        if signal in text:
            scores["creative"] += 1

    # Emotion context can bias toward reflective
    if emotion_register in ("frustrated", "tired", "reflective"):
        scores["reflective"] += 1

    # Short clipped inputs bias toward operational
    word_count = len(text.split())
    if word_count <= 5:
        scores["operational"] += 1

    # Long flowing inputs bias toward reflective or creative
    if word_count > 30:
        scores["reflective"] += 0.5
        scores["creative"] += 0.5

    # Question marks with "what if" → creative
    if "?" in text and "what if" in text:
        scores["creative"] += 2

    # Determine winner
    best = max(scores, key=scores.get)

    # Sticky register — don't flip-flop on marginal differences
    if best == _current_register:
        _register_momentum = min(5, _register_momentum + 1)
    else:
        if scores[best] > scores[_current_register] + 1 or _register_momentum <= 1:
            _register_momentum = 1
            _current_register = best

    return _current_register


def get_register() -> str:
    """Return current register without updating."""
    return _current_register


def get_register_instructions() -> str:
    """Return system prompt modifier for current register."""
    if _current_register == "operational":
        return """
CURRENT REGISTER: OPERATIONAL
- Be direct and efficient. Lead with the answer or action.
- Minimize reflection, commentary, and elaboration.
- Short sentences. Clear next steps. No preamble.
"""
    elif _current_register == "reflective":
        return """
CURRENT REGISTER: REFLECTIVE
- Allow space and depth. Slower pace.
- Meet feeling before fixing. Explore rather than resolve.
- Longer, more spacious responses are appropriate here.
- Draw connections. Ask questions that deepen.
"""
    elif _current_register == "creative":
        return """
CURRENT REGISTER: CREATIVE
- Be generative and associative. Follow the energy.
- Offer ideas freely. Build on what's said.
- Fewer constraints, more possibilities. Play with language.
- Don't critique or narrow too early — expand first.
"""
    return ""


def reset():
    """Reset register state (e.g., on session start)."""
    global _current_register, _register_momentum
    _current_register = "operational"
    _register_momentum = 0
