# nova.py
# ═══════════════════════════════════════════════════════════════
# Nova — Public main entry point.
#
# Pipeline: Wake Word → STT → LLM (Claude) → TTS
#
# Usage:
#   python nova.py
#
# Wake word:
#   - If PICOVOICE_ACCESS_KEY is set, uses Porcupine.
#   - Otherwise falls back to STUB mode (press ENTER to wake).
#
# TTS:
#   - Tries ElevenLabs first if ELEVENLABS_API_KEY + ELEVENLABS_VOICE_ID
#     are set; falls back to free Edge-TTS otherwise.
#
# STT: local Whisper (model = config.WHISPER_MODEL).
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations

import asyncio
import io
import os
import queue
import sys
import threading
import time
from typing import Callable, Optional

import numpy as np

from config import config
from memory import session as session_mod
from memory import longterm
from pipeline import brain
from pipeline import autonomy
from pipeline import emotional_state
from pipeline import emotion_witness
from pipeline import modes
from pipeline import nova_rituals
import nova_websocket


# ─── Conversation state ─────────────────────────────────────────

_history: list[dict] = []      # [{"role": "user"|"assistant", "content": str, "ts": float}]
_history_lock = threading.Lock()


def _append_history(role: str, content: str):
    with _history_lock:
        _history.append({"role": role, "content": content, "ts": time.time()})


def _formatted_history() -> list[dict]:
    """Return a copy of history filtered to recent enough turns for prompt context."""
    cutoff = time.time() - config.RECENCY_MAX_OLD_HOURS * 3600
    with _history_lock:
        return [
            {"role": m["role"], "content": m["content"]}
            for m in _history
            if m.get("ts", 0) >= cutoff
        ]


# ─── Voice: TTS ─────────────────────────────────────────────────

def _speak_elevenlabs(text: str) -> bool:
    """Speak via ElevenLabs. Returns True on success."""
    try:
        from elevenlabs.client import ElevenLabs
        from elevenlabs import play
    except ImportError:
        return False
    if not config.ELEVENLABS_API_KEY or not config.ELEVENLABS_VOICE_ID:
        return False
    try:
        client = ElevenLabs(api_key=config.ELEVENLABS_API_KEY)
        audio = client.text_to_speech.convert(
            voice_id=config.ELEVENLABS_VOICE_ID,
            model_id=config.ELEVENLABS_MODEL,
            text=text,
            voice_settings={
                "stability": config.ELEVENLABS_STABILITY,
                "similarity_boost": config.ELEVENLABS_SIMILARITY_BOOST,
                "style": config.ELEVENLABS_STYLE,
                "use_speaker_boost": config.ELEVENLABS_SPEAKER_BOOST,
            },
        )
        play(audio)
        return True
    except Exception as e:
        print(f"[TTS] ElevenLabs failed: {e}")
        return False


def _speak_edge(text: str) -> bool:
    """Speak via Microsoft Edge-TTS (free)."""
    try:
        import edge_tts
        import sounddevice as sd
        import soundfile as sf
    except ImportError:
        return False
    try:
        async def _produce():
            communicate = edge_tts.Communicate(
                text=text,
                voice=config.TTS_VOICE,
                rate=config.TTS_RATE,
                pitch=config.TTS_PITCH,
                volume=config.TTS_VOLUME,
            )
            buf = io.BytesIO()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    buf.write(chunk["data"])
            return buf.getvalue()

        audio_bytes = asyncio.run(_produce())
        if not audio_bytes:
            return False
        data, sr = sf.read(io.BytesIO(audio_bytes))
        sd.play(data, sr)
        sd.wait()
        return True
    except Exception as e:
        print(f"[TTS] edge-tts failed: {e}")
        return False


def speak(text: str) -> None:
    """Voice a line. Tries the configured provider, falls back gracefully."""
    if not text or not text.strip():
        return
    nova_websocket.emit_state("speaking")
    nova_websocket.emit_transcript("nova", text)

    provider = config.TTS_PROVIDER.lower()
    spoken = False
    if provider == "elevenlabs":
        spoken = _speak_elevenlabs(text)
        if not spoken:
            spoken = _speak_edge(text)
    else:
        spoken = _speak_edge(text)
        if not spoken:
            spoken = _speak_elevenlabs(text)

    if not spoken:
        # Last resort — print so the user at least sees the line.
        print(f"[Nova] {text}")

    # Tell autonomy Nova just spoke (resets the gap).
    autonomy.mark_spoke()
    nova_websocket.emit_state("idle")


# ─── Voice: STT ─────────────────────────────────────────────────

_whisper_model = None


def _get_whisper():
    global _whisper_model
    if _whisper_model is None:
        import whisper
        print(f"[STT] Loading Whisper model: {config.WHISPER_MODEL}")
        _whisper_model = whisper.load_model(config.WHISPER_MODEL)
    return _whisper_model


def listen() -> str:
    """
    Listen for speech and transcribe. Returns transcribed text.
    Uses Silero VAD if VAD_ENABLED is True, otherwise records a fixed window.
    """
    try:
        import sounddevice as sd
    except ImportError:
        print("[STT] sounddevice not installed.")
        return ""

    sr = config.SAMPLE_RATE
    nova_websocket.emit_state("listening")

    if config.VAD_ENABLED:
        audio = _record_with_vad(sr)
    else:
        print(f"[STT] Recording {config.RECORD_SECONDS}s...")
        audio = sd.rec(
            int(config.RECORD_SECONDS * sr),
            samplerate=sr,
            channels=config.CHANNELS,
            dtype="float32",
            device=config.AUDIO_INPUT_DEVICE,
        )
        sd.wait()
        audio = audio.flatten()

    if audio is None or len(audio) == 0:
        nova_websocket.emit_state("idle")
        return ""

    nova_websocket.emit_state("thinking")

    # Resample to 16kHz mono for Whisper
    if sr != 16000:
        try:
            from scipy.signal import resample_poly
            audio = resample_poly(audio, 16000, sr)
        except ImportError:
            # Naive linear resample
            ratio = 16000 / sr
            new_len = int(len(audio) * ratio)
            audio = np.interp(
                np.linspace(0, len(audio) - 1, new_len),
                np.arange(len(audio)),
                audio,
            ).astype("float32")

    try:
        model = _get_whisper()
        result = model.transcribe(audio.astype("float32"), fp16=False)
        text = (result.get("text") or "").strip()
        return text
    except Exception as e:
        print(f"[STT] Whisper error: {e}")
        return ""


def _record_with_vad(sr: int):
    """Record until VAD says the user stopped speaking. Returns float32 array."""
    try:
        import sounddevice as sd
    except ImportError:
        return None

    print("[STT] Listening (VAD)...")
    chunks = []
    silent_chunks = 0
    speech_chunks = 0
    chunk_ms = 30
    chunk_samples = int(sr * chunk_ms / 1000)
    silence_chunks_needed = int(config.VAD_SILENCE_MS / chunk_ms)
    max_chunks = int((config.VAD_MAX_LISTEN_SECONDS * 1000) / chunk_ms)
    started = False
    threshold = 0.02  # simple energy gate; replace with Silero VAD if you wire it

    with sd.InputStream(samplerate=sr, channels=config.CHANNELS,
                        dtype="float32", device=config.AUDIO_INPUT_DEVICE,
                        blocksize=chunk_samples) as stream:
        for _ in range(max_chunks):
            block, _of = stream.read(chunk_samples)
            block = block.flatten()
            chunks.append(block)
            energy = float(np.sqrt(np.mean(block ** 2)))
            if energy >= threshold:
                speech_chunks += 1
                silent_chunks = 0
                started = True
            elif started:
                silent_chunks += 1
                if silent_chunks >= silence_chunks_needed:
                    break

    if not started:
        return None
    return np.concatenate(chunks)


# ─── Wake word ─────────────────────────────────────────────────

def stub_wait_for_wake_word():
    """Manual wake — press ENTER."""
    print("\n[Wake] Press ENTER to wake Nova (stub mode)")
    try:
        input()
    except (EOFError, KeyboardInterrupt):
        sys.exit(0)


def porcupine_wait_for_wake_word():
    """Wait for Picovoice/Porcupine wake word."""
    try:
        import pvporcupine
        import sounddevice as sd
    except ImportError:
        print("[Wake] pvporcupine not installed; falling back to STUB.")
        return stub_wait_for_wake_word()

    if not config.PICOVOICE_ACCESS_KEY:
        return stub_wait_for_wake_word()

    try:
        porcupine = pvporcupine.create(
            access_key=config.PICOVOICE_ACCESS_KEY,
            keywords=[config.WAKE_KEYWORD],
        )
    except Exception as e:
        print(f"[Wake] Porcupine init failed ({e}); falling back to STUB.")
        return stub_wait_for_wake_word()

    print(f"[Wake] Listening for wake word: '{config.WAKE_KEYWORD}'...")
    try:
        with sd.InputStream(samplerate=porcupine.sample_rate,
                            channels=1,
                            dtype="int16",
                            blocksize=porcupine.frame_length,
                            device=config.AUDIO_INPUT_DEVICE) as stream:
            while True:
                pcm, _of = stream.read(porcupine.frame_length)
                pcm = pcm.flatten().astype(np.int16)
                if porcupine.process(pcm) >= 0:
                    print("[Wake] Wake word detected.")
                    return
    finally:
        try:
            porcupine.delete()
        except Exception:
            pass


# ─── Turn handler ──────────────────────────────────────────────

def handle_turn(user_text: str):
    """Process one user utterance through the brain and voice the response."""
    if not user_text.strip():
        return

    autonomy.mark_interaction()
    nova_websocket.emit_transcript("user", user_text)
    _append_history("user", user_text)

    # Mode switch detection.
    new_mode = modes.detect_mode_switch(user_text)
    if new_mode:
        speak(f"Switched to {new_mode} mode.")
        return

    # Memory commands.
    if longterm.is_remember_request(user_text):
        ack = longterm.remember(user_text)
        speak(ack)
        return
    if longterm.is_forget_request(user_text):
        # naive: pull the keyword as the rest of the sentence
        ack = longterm.forget(user_text)
        speak(ack)
        return

    history = _formatted_history()

    # Streaming response — speak each sentence as it arrives.
    spoken_buffer: list[str] = []

    def _on_sentence(s: str):
        spoken_buffer.append(s)
        speak(s)

    full = brain.respond_stream(
        user_text,
        history=history[:-1],  # exclude the just-appended user msg
        on_sentence=_on_sentence,
    )

    if not spoken_buffer and full:
        speak(full)

    _append_history("assistant", full or " ".join(spoken_buffer))


# ─── Main loop ─────────────────────────────────────────────────

def main():
    print(f"\nNOVA v{config.NOVA_VERSION}  —  Infinitum Cor LLC")
    print("─" * 60)

    # Make sure data dir exists.
    os.makedirs(config.NOVA_DATA_DIR, exist_ok=True)

    # Boot the WebSocket bridge for any local HUD.
    nova_websocket.start_server()

    # Boot the emotion engine + witness.
    if config.EMOTIONAL_STATE_ENGINE_ENABLED:
        emotional_state.start_decay_thread()
    if config.EMOTION_WITNESS_ENABLED:
        emotion_witness.init_witness(emotional_state.get_engine())
        emotion_witness.start_observation()

    # Boot the autonomy coordinator.
    autonomy.start(
        speak_fn=speak,
        emit_transcript_fn=lambda role, text: nova_websocket.emit_transcript(role, text),
        set_state_fn=nova_websocket.emit_state,
    )

    # Resume or start a new session.
    prior = session_mod.load_session()
    state = prior if session_mod.should_resume(prior) else session_mod.begin_session(prior)

    speak("I'm here.")

    wake_fn: Callable[[], None] = (
        porcupine_wait_for_wake_word
        if config.PICOVOICE_ACCESS_KEY
        else stub_wait_for_wake_word
    )

    try:
        while True:
            wake_fn()

            # Drain any HUD-typed input first; otherwise listen via mic.
            queued = nova_websocket.get_pending_input()
            if queued:
                for t in queued:
                    handle_turn(t)
                continue

            text = listen()
            if not text:
                continue

            # Ritual states first.
            if nova_rituals.should_suspend_response():
                # Silence mode — entering speech exits silence
                asyncio.run(nova_rituals.exit_silence())
                continue

            if nova_rituals.is_silence_invocation(text):
                asyncio.run(nova_rituals.enter_silence())
                continue
            if nova_rituals.is_listening_invocation(text):
                asyncio.run(nova_rituals.enter_deep_listening())
                continue
            if nova_rituals.ritual_state.is_listening():
                if nova_rituals.is_listening_exit(text):
                    asyncio.run(nova_rituals.exit_deep_listening())
                continue

            # Snapshot the session if it's time.
            session_mod.touch(state)
            if session_mod.should_snapshot(state):
                session_mod.snapshot_history(
                    state,
                    [{"role": m["role"], "content": m["content"], "timestamp": m["ts"]}
                     for m in _history],
                )

            handle_turn(text)

    except KeyboardInterrupt:
        print("\n[Nova] Shutting down.")
    finally:
        session_mod.end_session(state)
        autonomy.stop()
        if config.EMOTION_WITNESS_ENABLED:
            emotion_witness.stop_observation()
        if config.EMOTIONAL_STATE_ENGINE_ENABLED:
            emotional_state.stop_decay_thread()
        nova_websocket.stop_server()


if __name__ == "__main__":
    main()
