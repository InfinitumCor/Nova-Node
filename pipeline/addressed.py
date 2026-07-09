# pipeline/addressed.py
# ═══════════════════════════════════════════════════════════════
# ADDRESSED-TO-ME JUDGMENT
#
# People work aloud near a voice companion — read numbers to a support
# agent, dictate an address, mutter at a screen. A companion that
# answers *everything* it hears becomes noise; one that goes silent
# unpredictably becomes untrustworthy. So Nova judges: was that meant
# for me?
#
# The governing principle: SILENCE MUST BE EARNED BY EVIDENCE.
# The default verdict is "addressed" — she only stays quiet when the
# utterance carries positive signs it wasn't for her (dictation,
# talking to a third party, a stray acknowledgment long after the
# conversation went cold). Saying "Nova" anywhere overrides
# everything. Uncertain turns are answered, never dropped.
#
# Fast heuristics only — no LLM call, so the judgment costs ~0 ms.
# Every quiet turn is recorded to drop_log ("not_addressed") so bad
# judgments are visible and tunable.
# ═══════════════════════════════════════════════════════════════

import re
import time

try:
    from config import config as _config
except Exception:
    _config = None

_last_spoke_at = 0.0
_ambient_streak = 0


def nova_spoke() -> None:
    """Call whenever Nova finishes speaking — feeds the momentum rule."""
    global _last_spoke_at
    _last_spoke_at = time.time()


def seconds_since_spoke() -> float:
    return (time.time() - _last_spoke_at) if _last_spoke_at else 1e9


def note_ambient() -> bool:
    """Record a quiet turn. True if it's the FIRST in a streak (the
    caller may surface a one-time 'staying quiet' note)."""
    global _ambient_streak
    _ambient_streak += 1
    return _ambient_streak == 1


def note_addressed() -> None:
    global _ambient_streak
    _ambient_streak = 0


# ── Evidence patterns ─────────────────────────────────────────────

# Dictation / reading aloud: long digit runs, codes, spelled domains
# and emails — the texture of working with an account screen or a
# support call, not of talking to her.
_DICTATION = re.compile(
    r"\d{4,}"
    r"|\b\d+[\s-]\d+[\s-]\d+\b"
    r"|\bdot\s?(?:com|org|net|xyz|io)\b"
    r"|\.(?:com|org|net|xyz|io)\b"
    r"|\bat\s?gmail\b|@"
    r"|\bzip\s?code\b|\bpasscode\b|\bthe\s+pin\b|\bpin\s+is\b"
    r"|\bconfirmation\s+(?:number|code)\b|\baccount\s+number\b",
    re.IGNORECASE,
)

# Talking to someone who is not her.
_THIRD_PARTY = re.compile(
    r"\bhe\s+said\b|\bshe\s+said\b|\btell\s+(?:him|her|them)\b"
    r"|\bsir\b|\bma'?am\b|\byou\s+guys\b"
    r"|\bhey\s+(?:man|dude|buddy)\b|\bthanks\s+(?:man|dude|buddy)\b",
    re.IGNORECASE,
)

# Second-person engagement — a question or request aimed at *you*.
_SECOND_PERSON = re.compile(
    r"\b(?:are|were|can|could|will|would|do|does|did|have|has|should)\s+you\b"
    r"|\bwhat\s+(?:do|did|are|about)\s+you\b|\byou\s+(?:think|know|feel|remember|see)\b"
    r"|\byour\b",
    re.IGNORECASE,
)

# Imperatives she owns — a command shape is a request even without "you".
_IMPERATIVE = re.compile(
    r"^(?:please\s+)?(?:tell|show|give|remind|read|play|pause|open|close|"
    r"search|find|look|explain|help|check|start|stop|run|save|remember|"
    r"forget|describe|summarize|translate)\b",
    re.IGNORECASE,
)

# Stray acknowledgments — talk-to-self texture when nothing is in
# flight. Matched as a word set so punctuation/combinations still read
# as acks ("Okay, perfect." → {okay, perfect} ⊆ vocab).
_ACK_WORDS = {
    "okay", "ok", "alright", "all", "right", "perfect", "yep", "yes",
    "yeah", "no", "nope", "got", "it", "sounds", "good", "there", "we",
    "go", "nice", "cool", "uh", "huh", "mhm", "hmm", "let's", "see",
    "one", "sec", "second", "hold", "on", "sweet", "great", "done",
}


def _is_ack(low: str) -> bool:
    words = re.findall(r"[a-z']+", low)
    return bool(words) and len(words) <= 3 and set(words) <= _ACK_WORDS


def _momentum_window() -> float:
    return float(getattr(_config, "ADDRESSED_MOMENTUM_SECONDS", 25.0) or 25.0)


def judge(text: str) -> tuple:
    """Return (verdict, reason) where verdict is 'addressed' | 'ambient'.

    Rule order matters: naming her wins outright; hard ambient evidence
    (dictation / third party) beats momentum; direct engagement beats
    everything below it; the default is ADDRESSED."""
    t = (text or "").strip()
    if not t:
        return ("ambient", "empty")
    low = t.lower()
    in_exchange = seconds_since_spoke() < _momentum_window()

    # 1. She was named — always for her.
    if "nova" in low:
        return ("addressed", "named")

    # 2. Direct second-person engagement — for her, even mid-dictation
    #    ("can you check this number?").
    if _SECOND_PERSON.search(t):
        return ("addressed", "second-person")

    # 3. Hard ambient evidence.
    if _DICTATION.search(t):
        return ("ambient", "dictation")
    if _THIRD_PARTY.search(t):
        return ("ambient", "third-party")

    # 4. A command shape is a request to her.
    if _IMPERATIVE.match(t):
        return ("addressed", "imperative")

    # 5. Stray short acknowledgment: an answer to her if she just spoke,
    #    talk-to-self if the room has been quiet a while.
    if _is_ack(low):
        return ("addressed", "ack-in-exchange") if in_exchange \
            else ("ambient", "stray-ack")

    # 6. Everything else: if the exchange is warm, it's conversation;
    #    if the room went cold, it still defaults to addressed —
    #    silence must be earned.
    return ("addressed", "momentum" if in_exchange else "default")
