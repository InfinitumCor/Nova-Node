# pipeline/brain.py
# ═══════════════════════════════════════════════════════════════
# Nova's reasoning router. Public edition.
#
# Takes a user utterance plus conversation history, assembles the
# system prompt from all active modifiers (mode, register, emotion,
# witness), and calls Claude. Streams responses back sentence by
# sentence when streaming is enabled.
#
# The Prime brain.py is much larger — it routes to vault search,
# vision, mode-specific tool calls, and proprietary integrations.
# The Public brain is the bare reasoning core: prompt + LLM + return.
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Callable, Iterable, List, Optional
from zoneinfo import ZoneInfo

import anthropic

from config import config
from pipeline import modes, register
from pipeline import emotion_state, emotional_state, emotion_witness


# ── Client (lazy) ───────────────────────────────────────────────

_client: Optional[anthropic.Anthropic] = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        if not config.ANTHROPIC_API_KEY:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. "
                "Copy .env.example to .env and fill in your key."
            )
        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


# ── System prompt assembly ──────────────────────────────────────

def _authoritative_time_block() -> str:
    """Inject the current local time into the system prompt so the
    model doesn't drift on DST or guess the time zone."""
    try:
        tz = ZoneInfo(config.TIMEZONE)
        now = datetime.now(tz)
        return (
            f"\nCurrent date and time: {now.strftime('%A, %B %d, %Y at %I:%M %p')} "
            f"({tz.key}). This time is authoritative. Do NOT adjust it."
        )
    except Exception:
        return ""


def build_system_prompt() -> str:
    """
    Assemble the full system prompt for one turn:
      - base persona (config.NOVA_SYSTEM_PROMPT)
      - current response mode instructions
      - current register instructions
      - emotional register modifier
      - emotional tone profile modifier
      - witness layer pattern observations (read-only)
      - authoritative current time
    """
    parts: List[str] = [config.NOVA_SYSTEM_PROMPT.strip()]

    parts.append("\nRESPONSE MODE:\n" + modes.get_mode_instructions())

    if config.REGISTER_MATCHING_ENABLED:
        reg_block = register.get_register_instructions()
        if reg_block.strip():
            parts.append(reg_block)

    emo_block = emotion_state.get_emotion_instructions()
    if emo_block.strip():
        parts.append(emo_block)

    if config.EMOTIONAL_STATE_ENGINE_ENABLED:
        tone_block = emotional_state.get_emotion_profile_instructions()
        if tone_block.strip():
            parts.append(tone_block)

    if config.EMOTION_WITNESS_ENABLED:
        witness_block = emotion_witness.get_witness_instructions()
        if witness_block.strip():
            parts.append(witness_block)

    parts.append(_authoritative_time_block())

    return "\n".join(p for p in parts if p)


# ── History formatting ──────────────────────────────────────────

def format_history(history: List[dict]) -> List[dict]:
    """
    Turn an internal history list into Claude's message format.
    Each entry should be {'role': 'user'|'assistant', 'content': str}.
    """
    out = []
    for msg in history:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role not in ("user", "assistant"):
            role = "user"
        out.append({"role": role, "content": content})
    return out


# ── Sentence streaming ──────────────────────────────────────────

_SENTENCE_END = re.compile(r"(.+?[\.!?])(\s|$)")


def _sentences(buffer: str) -> tuple[list[str], str]:
    """
    Pull complete sentences off the front of `buffer`. Returns
    (sentences, remaining_buffer).
    """
    sentences: list[str] = []
    while True:
        m = _SENTENCE_END.search(buffer)
        if not m:
            break
        sentences.append(m.group(1).strip())
        buffer = buffer[m.end():]
    return sentences, buffer


# ── Main entry points ───────────────────────────────────────────

def respond(user_text: str,
            history: Optional[List[dict]] = None,
            voice_context: str = "") -> str:
    """
    Generate Nova's response synchronously. Returns the full text.
    For streaming TTS, use `respond_stream` instead.
    """
    history = history or []

    if config.REGISTER_MATCHING_ENABLED:
        register.detect_register(user_text, emotion_state.get_register())
    emotion_state.update(user_text, voice_context)

    messages = format_history(history) + [
        {"role": "user", "content": user_text}
    ]

    client = _get_client()
    resp = client.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=config.ANTHROPIC_MAX_TOKENS,
        system=build_system_prompt(),
        messages=messages,
    )

    text = "".join(
        block.text for block in resp.content if getattr(block, "type", "") == "text"
    ).strip()
    return text


def respond_stream(user_text: str,
                   history: Optional[List[dict]] = None,
                   voice_context: str = "",
                   on_sentence: Optional[Callable[[str], None]] = None,
                   on_complete: Optional[Callable[[str], None]] = None) -> str:
    """
    Stream Nova's response. Calls `on_sentence(text)` for each complete
    sentence as soon as it's available (use this to drive streaming TTS).
    Calls `on_complete(full_text)` once at the end.

    Returns the full response text. Falls back to non-streaming respond()
    if streaming is disabled.
    """
    history = history or []

    if not config.STREAMING_TTS_ENABLED:
        text = respond(user_text, history, voice_context)
        if on_complete:
            on_complete(text)
        return text

    if config.REGISTER_MATCHING_ENABLED:
        register.detect_register(user_text, emotion_state.get_register())
    emotion_state.update(user_text, voice_context)

    messages = format_history(history) + [
        {"role": "user", "content": user_text}
    ]

    client = _get_client()

    buffer = ""
    full_text = ""
    first_flushed = False

    with client.messages.stream(
        model=config.ANTHROPIC_MODEL,
        max_tokens=config.ANTHROPIC_MAX_TOKENS,
        system=build_system_prompt(),
        messages=messages,
    ) as stream:
        for delta in stream.text_stream:
            if not delta:
                continue
            buffer += delta
            full_text += delta

            # Hold the first sentence until it crosses the min length
            # threshold to avoid TTS-ing one-word interjections.
            if not first_flushed and len(buffer.strip()) < config.STREAMING_MIN_FIRST_SENTENCE_CHARS:
                continue

            sentences, buffer = _sentences(buffer)
            for s in sentences:
                if s:
                    first_flushed = True
                    if on_sentence:
                        try:
                            on_sentence(s)
                        except Exception as e:
                            print(f"[brain] on_sentence error: {e}")

    # Flush any tail
    tail = buffer.strip()
    if tail and on_sentence:
        try:
            on_sentence(tail)
        except Exception as e:
            print(f"[brain] on_sentence tail error: {e}")

    if on_complete:
        try:
            on_complete(full_text.strip())
        except Exception as e:
            print(f"[brain] on_complete error: {e}")

    return full_text.strip()
