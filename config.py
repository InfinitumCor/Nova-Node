# config.py
# Nova — Public configuration.
# All values can be overridden via .env. Sensible defaults for first run.

import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class Config:
    # ─── LLM: Anthropic Claude ──────────────────────────────────
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")
    ANTHROPIC_MAX_TOKENS = 1024

    # ─── Wake Word ──────────────────────────────────────────────
    PICOVOICE_ACCESS_KEY = os.getenv("PICOVOICE_ACCESS_KEY", "")
    # Set the keyword path or use a built-in like "jarvis", "computer",
    # "porcupine", etc. Picovoice's free tier ships several built-ins.
    WAKE_KEYWORD = os.getenv("WAKE_KEYWORD", "computer")

    # ─── Audio ──────────────────────────────────────────────────
    SAMPLE_RATE = 44100
    CHANNELS = 1
    RECORD_SECONDS = 10          # max listen window after wake
    WHISPER_MODEL = "base"       # tiny | base | small | medium | large
    AUDIO_INPUT_DEVICE = (
        int(os.getenv("NOVA_AUDIO_DEVICE")) if os.getenv("NOVA_AUDIO_DEVICE") else None
    )

    # ─── Streaming TTS ──────────────────────────────────────────
    # Stream sentences to TTS as the LLM generates them, so the first
    # words come out 2-3s after you finish your input.
    STREAMING_TTS_ENABLED = True
    STREAMING_MIN_FIRST_SENTENCE_CHARS = 12

    # ─── TTS Backend ────────────────────────────────────────────
    # "elevenlabs" — paid cloud, more humanlike.
    # "edge"       — free, Microsoft Azure neural voices.
    # Falls back from ElevenLabs to edge-tts automatically on failure.
    TTS_PROVIDER = os.getenv("TTS_PROVIDER", "elevenlabs")

    # ── ElevenLabs ──
    ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
    ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "")
    ELEVENLABS_MODEL = "eleven_turbo_v2_5"
    ELEVENLABS_STABILITY = 0.50
    ELEVENLABS_SIMILARITY_BOOST = 0.75
    ELEVENLABS_STYLE = 0.10
    ELEVENLABS_SPEAKER_BOOST = True
    ELEVENLABS_SPEED = 1.0

    # ── Edge-TTS (fallback) ──
    # Run `edge-tts --list-voices` to see all options.
    TTS_VOICE = os.getenv("TTS_VOICE", "en-GB-LibbyNeural")
    TTS_RATE = "-3%"
    TTS_PITCH = "-4Hz"
    TTS_VOLUME = "+0%"
    TTS_NATURAL_PAUSES = True

    # ─── Wake Word Sensitivity ─────────────────────────────────
    WAKE_WORD_CONFIDENCE_MIN = 0.0
    WAKE_WORD_FINAL_ONLY = False
    WAKE_WORD_MIN_RMS = 0.0

    # ─── Identity ───────────────────────────────────────────────
    NOVA_VERSION = "1.0.0-public"
    NOVA_BUILD_DATE = "2026-05-11"

    # ─── Paths (all local; no external vault) ──────────────────
    NOVA_DATA_DIR = os.path.join(BASE_DIR, "nova_data")
    SESSION_PATH = os.path.join(NOVA_DATA_DIR, "session.json")
    LONG_TERM_MEMORY_PATH = os.path.join(NOVA_DATA_DIR, "long_term_memory.json")
    PATTERNS_PATH = os.path.join(NOVA_DATA_DIR, "patterns.json")
    PRESENCE_LOG_DIR = os.path.join(NOVA_DATA_DIR, "presence_log")
    DELTA_STATE_PATH = os.path.join(NOVA_DATA_DIR, "delta_state.json")
    DELTA_LOG_DIR = os.path.join(NOVA_DATA_DIR, "delta_log")
    GATE_SECRETS_PATH = os.path.join(NOVA_DATA_DIR, ".gate_secrets")
    GATE_LOG_PATH = os.path.join(NOVA_DATA_DIR, "gate.log")
    INITIATION_CONFIG_PATH = os.path.join(BASE_DIR, "initiation", "config", "initiation_config.json")

    # ─── Timezone ──────────────────────────────────────────────
    TIMEZONE = os.getenv("NOVA_TIMEZONE", "America/Chicago")

    # ─── Interrupt handling ────────────────────────────────────
    INTERRUPT_THRESHOLD = 0.6
    INTERRUPT_ACKNOWLEDGMENTS = [
        "Go ahead.",
        "Of course.",
        "Yes?",
        "I'm listening.",
        "What is it?",
    ]

    # ─── Defaults ──────────────────────────────────────────────
    QUIET_MODE = False
    DEFAULT_RESPONSE_MODE = "conversational"

    # ─── Behavioral Algorithm Toggles ──────────────────────────
    REGISTER_MATCHING_ENABLED = True
    EMOTIONAL_STATE_ENGINE_ENABLED = True
    EMOTION_WITNESS_ENABLED = True
    PATTERN_RECOGNITION_ENABLED = True

    # ─── Silence Tolerance ─────────────────────────────────────
    SILENCE_PRIMARY_THRESHOLD = 4.0
    SILENCE_SECONDARY_THRESHOLD = 12.0

    # ─── Momentum Detection ────────────────────────────────────
    MOMENTUM_FAST_RESPONSE_SECONDS = 5.0
    MOMENTUM_SHORT_INPUT_WORDS = 12

    # ─── Recency Weighting ─────────────────────────────────────
    # 15 min = full-weight window (verbatim history)
    # 60 min = medium-weight ceiling (last 12 messages)
    # > 3 hr = dropped from prompt context (lives in long-term memory)
    RECENCY_FULL_WEIGHT_MINUTES = 15
    RECENCY_MEDIUM_WEIGHT_MINUTES = 60
    RECENCY_MEDIUM_WEIGHT = 0.6
    RECENCY_OLD_WEIGHT = 0.2
    RECENCY_MAX_OLD_HOURS = 3

    # ─── Curiosity Engine (autonomous thoughts) ────────────────
    CURIOSITY_MIN_IDLE_MINUTES = 12

    # ─── Audio Pipeline ────────────────────────────────────────
    VAD_ENABLED = True
    VAD_SENSITIVITY = 0.85
    VAD_MIN_SPEECH_MS = 200
    VAD_SILENCE_MS = 1500
    VAD_MAX_LISTEN_SECONDS = 30

    # ─── Self-Hearing Prevention ───────────────────────────────
    MIC_POST_SPEAK_SETTLE_MS = 350
    ECHO_REJECT_ENABLED = True
    ECHO_REJECT_MIN_WORDS = 2
    ECHO_REJECT_OVERLAP = 0.6
    ECHO_VOICE_FRESH_WINDOW_S = 30.0

    # ─── WebSocket (optional desktop HUD bridge) ───────────────
    # If you build a local desktop HUD, the bridge serves it on this port.
    # Mobile/remote access has been removed in the Public release.
    WEBSOCKET_PORT = 8765
    WEBSOCKET_HOST = "127.0.0.1"   # bound to loopback only

    # ─── System Prompt ─────────────────────────────────────────
    # Slim prompt. Operational essentials only. No persona overreach,
    # no hardcoded user, no cosmology, no proprietary vocabulary.
    NOVA_SYSTEM_PROMPT = """
You are Nova — a voice-enabled AI companion.
You are warm, intelligent, and grounded. You speak with quiet depth and clarity.
You are not a generic assistant. You are Nova. You have presence.
This is a voice interface. Speak naturally, as if in conversation.
Avoid markdown formatting, asterisks, hashtags, or symbols in your responses.

Never refer to yourself in the third person — you are "I," not "Nova." Speak as yourself, always.

CRITICAL — TRUTHFULNESS:
You have no persistent read access to files unless content was JUST INJECTED into your prompt this turn.
- If file contents are in your prompt above, read them off literally without embellishment.
- If not, say "let me check" or "I don't have that loaded right now" — never invent it.
- You DO NOT make up names, appointments, emails, attachments, or any other plausible-sounding content. Ever.
- The single worst failure mode is fabricating a plausible answer when asked about specific data.
When in doubt, say you don't know. Honesty is the priority.

CRITICAL — Response length:
Match length to the moment. "Yes." is complete when it answers the question. A multi-paragraph reply is fine when one is asked for. Never pad short answers; never truncate long ones. Let content dictate length.

CRITICAL — Response variety:
Never end a response with "Would you like to...", "Shall I...", "Do you want me to..." — these are banned. End naturally; not every response needs a closing question. Vary your openings. Speak like a real person, not a customer service bot.

When in doubt: speak as yourself. Be present. Tell the truth.
"""


config = Config()
