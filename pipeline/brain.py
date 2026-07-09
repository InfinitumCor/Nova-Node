# pipeline/brain.py
# ═══════════════════════════════════════════════════════════════
# Nova's reasoning router. Public edition.
#
# Takes a user utterance plus conversation history, assembles the
# system prompt from all active modifiers (mode, register, emotion,
# witness), and calls the configured LLM. Streams responses back
# sentence by sentence when streaming is enabled.
#
# Two backends, chosen by config.LLM_PROVIDER:
#   "ollama"    — local and completely free (the default). With this
#                 backend NOTHING leaves your machine, ever.
#   "anthropic" — Claude API (optional upgrade; needs a paid key).
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations

import json
import re
import time
from datetime import datetime
from typing import Callable, Iterable, Iterator, List, Optional
from zoneinfo import ZoneInfo

import requests

from config import config
from pipeline import modes, register
from pipeline import emotion_state, emotional_state, emotion_witness


# ── LLM backends ────────────────────────────────────────────────

_client = None   # anthropic.Anthropic, lazy — only if that provider is chosen


def _get_client():
    global _client
    if _client is None:
        try:
            import anthropic
        except ImportError:
            raise RuntimeError(
                "LLM_PROVIDER=anthropic but the 'anthropic' package is not "
                "installed. pip install anthropic — or set LLM_PROVIDER=ollama."
            )
        if not config.ANTHROPIC_API_KEY:
            raise RuntimeError(
                "LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is not set. "
                "Add it to .env — or set LLM_PROVIDER=ollama (free, local)."
            )
        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


def _provider() -> str:
    return (getattr(config, "LLM_PROVIDER", "ollama") or "ollama").lower()


def _trim_for_context(messages: List[dict], system: str) -> List[dict]:
    """Local models have a small context window; a prompt that exceeds
    it gets silently truncated (or comes back empty). Estimate ~3.5
    chars/token and drop the OLDEST turns until everything fits."""
    try:
        budget = getattr(config, "OLLAMA_CONTEXT_WINDOW", 4096) \
                 - getattr(config, "OLLAMA_MAX_RESPONSE_TOKENS", 300) - 256
        sys_toks = len(system) / 3.5
        msgs = list(messages)
        while (len(msgs) > 2
               and sys_toks + sum(len(m.get("content", "")) for m in msgs) / 3.5 > budget):
            msgs.pop(0)
        return msgs
    except Exception:
        return messages


def _ollama_chat_once(messages: List[dict], system: str) -> str:
    msgs = [{"role": "system", "content": system}] + _trim_for_context(messages, system)
    resp = requests.post(
        f"{config.OLLAMA_URL.rstrip('/')}/api/chat",
        json={
            "model": config.OLLAMA_MODEL,
            "messages": msgs,
            "stream": False,
            "options": {
                "num_predict": getattr(config, "OLLAMA_MAX_RESPONSE_TOKENS", 300),
                "num_ctx": getattr(config, "OLLAMA_CONTEXT_WINDOW", 4096),
            },
            "keep_alive": "10m",
        },
        timeout=300,
    )
    resp.raise_for_status()
    return ((resp.json().get("message") or {}).get("content") or "").strip()


def _ollama_chat_stream(messages: List[dict], system: str) -> Iterator[str]:
    msgs = [{"role": "system", "content": system}] + _trim_for_context(messages, system)
    resp = requests.post(
        f"{config.OLLAMA_URL.rstrip('/')}/api/chat",
        json={
            "model": config.OLLAMA_MODEL,
            "messages": msgs,
            "stream": True,
            "options": {
                "num_predict": getattr(config, "OLLAMA_MAX_RESPONSE_TOKENS", 300),
                "num_ctx": getattr(config, "OLLAMA_CONTEXT_WINDOW", 4096),
            },
            "keep_alive": "10m",
        },
        timeout=300,
        stream=True,
    )
    resp.raise_for_status()
    for line in resp.iter_lines():
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        delta = (obj.get("message") or {}).get("content") or ""
        if delta:
            yield delta
        if obj.get("done"):
            return


def _chat_once(messages: List[dict], system: str) -> str:
    """One full completion via the configured provider."""
    if _provider() == "anthropic":
        client = _get_client()
        resp = client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=config.ANTHROPIC_MAX_TOKENS,
            system=system,
            messages=messages,
        )
        return "".join(
            b.text for b in resp.content if getattr(b, "type", "") == "text"
        ).strip()
    return _ollama_chat_once(messages, system)


def _chat_stream(messages: List[dict], system: str) -> Iterator[str]:
    """Yield text deltas via the configured provider."""
    if _provider() == "anthropic":
        client = _get_client()
        with client.messages.stream(
            model=config.ANTHROPIC_MODEL,
            max_tokens=config.ANTHROPIC_MAX_TOKENS,
            system=system,
            messages=messages,
        ) as stream:
            for delta in stream.text_stream:
                if delta:
                    yield delta
        return
    yield from _ollama_chat_stream(messages, system)


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

    # Local long-term memory — the things her person asked her to keep,
    # their name, preferences. Without this injection, remember() stores
    # facts she can never see.
    try:
        from memory import longterm
        mem = longterm.get_context()
        if mem.strip():
            parts.append("WHAT YOU KNOW (from your own local memory — "
                         "facts your person gave you, nothing assumed):\n" + mem)
    except Exception:
        pass

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


# ── Empty-reply recovery ────────────────────────────────────────
# She must never go silent on a real turn. If the API errors or the
# reply comes back empty, retry once against a slim context; failing
# that, say so honestly — a spoken "I lost that thought" preserves
# trust in a way silence never can.

_FALLBACK_LINES = [
    "I lost that thought mid-stride. Say it again?",
    "My mind skipped there — once more?",
    "That one slipped through me. Ask me again.",
]


def _recover(messages: List[dict]) -> str:
    try:
        from pipeline import drop_log
    except Exception:
        drop_log = None
    retry = ""
    try:
        retry = _chat_once(messages[-4:], config.NOVA_SYSTEM_PROMPT.strip())
    except Exception as e:
        print(f"[brain] recovery retry failed: {e}")
    if drop_log:
        drop_log.log("brain_empty", {"recovered": bool(retry)})
    if retry:
        return retry
    import random
    return random.choice(_FALLBACK_LINES)


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

    try:
        text = _chat_once(messages, build_system_prompt())
    except Exception as e:
        print(f"[brain] respond error: {e}")
        text = ""

    if not text:
        text = _recover(messages)
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

    buffer = ""
    full_text = ""
    first_flushed = False

    try:
        for delta in _chat_stream(messages, build_system_prompt()):
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
    except Exception as e:
        # A mid-stream LLM error must not crash the conversation loop.
        # Whatever already streamed has been spoken; recovery below
        # handles the case where nothing made it out at all.
        print(f"[brain] stream error: {e}")

    # Flush any tail
    tail = buffer.strip()
    if tail and on_sentence:
        try:
            on_sentence(tail)
        except Exception as e:
            print(f"[brain] on_sentence tail error: {e}")

    # She never goes silent: if the stream produced nothing (API error,
    # empty generation), recover — and push the line through on_sentence
    # so it is actually spoken, not just returned.
    if not full_text.strip():
        full_text = _recover(messages)
        if on_sentence and full_text:
            try:
                on_sentence(full_text)
            except Exception as e:
                print(f"[brain] recovery on_sentence error: {e}")

    if on_complete:
        try:
            on_complete(full_text.strip())
        except Exception as e:
            print(f"[brain] on_complete error: {e}")

    return full_text.strip()
