# Nova

> Voice-enabled AI companion. Wake word → Speech-to-text → LLM → TTS.

Nova is a local voice companion built around a single principle: **silence is the default**. She doesn't speak unless spoken to, unless one of her own boundary-respecting triggers fires. She has presence, an emotional model that observes itself, response modes you can switch into mid-conversation, and a quiet ritual layer for shared silence and deep listening.

This is the open-source release. Base capability only.

— Infinitum Cor LLC

---

## Pipeline

```
Wake Word  →  Speech-to-text  →  LLM (Claude)  →  Text-to-speech
(Porcupine    (local Whisper)    (Anthropic API)   (Edge-TTS, free)
 or STUB)
```

Everything runs locally except the LLM call. STT, wake detection, and TTS playback all happen on your machine.

---

## Setup

```bash
# 1. Create and activate a virtual environment
python -m venv venv
# Windows:  venv\Scripts\activate
# macOS/Linux: source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy the env template and fill in your key
cp .env.example .env
# Edit .env — minimum required: ANTHROPIC_API_KEY

# 4. Run
python nova.py
```

### Required API keys

| Service | Why | Where |
|---|---|---|
| **Anthropic** | LLM reasoning | https://console.anthropic.com/settings/keys |

Voice synthesis uses the free Microsoft Edge-TTS voices by default — no account, no key, no signup.

### Optional

| Service | Why | Where |
|---|---|---|
| **Picovoice** | "Wake on word" via Porcupine. Without this, Nova runs in STUB mode (press ENTER to wake). | https://picovoice.ai |
| **ElevenLabs** | Premium voice quality. Drop `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` into `.env` to use it; Nova falls back to Edge-TTS automatically if either is missing. | https://elevenlabs.io |

---

## Voice ID lookup (ElevenLabs only)

If you're using ElevenLabs, voices each have an ID. To list yours:

```bash
python -c "from elevenlabs.client import ElevenLabs; c = ElevenLabs(api_key='YOUR_KEY'); [print(v.voice_id, v.name) for v in c.voices.get_all().voices]"
```

Drop the ID you want into `ELEVENLABS_VOICE_ID` in `.env`.

If you're using Edge-TTS (the default), there's nothing to configure — Nova picks a voice and runs.

---

## Architecture

```
nova-public/
├── nova.py                       # Main entry point — wake/STT/turn loop
├── nova_curiosity.py             # Delta-driven autonomous-thought engine
├── nova_websocket.py             # Loopback HUD bridge (ws://127.0.0.1:8765)
├── config.py                     # All tunables, system prompt, paths
├── requirements.txt
├── .env.example
│
├── pipeline/
│   ├── brain.py                  # System prompt assembly + Claude call
│   ├── modes.py                  # 7 response modes (brief/deep/creative/...)
│   ├── register.py               # Auto-detect operational/reflective/creative
│   ├── autonomy.py               # Boundaries: silence-by-default, night, gaps
│   ├── presence.py               # "Step away" mode — Nova journals silently
│   ├── nova_rituals.py           # Silence Mode + Deep Listening
│   ├── speech_gate.py            # Central allow/deny for unprompted speech
│   ├── emotional_state.py        # 6-state blend (present/warm/curious/...)
│   ├── emotion_state.py          # 11-register text/voice carry-forward
│   ├── emotion_witness.py        # Read-only meta-observer (never writes back)
│   ├── delta_detector.py         # Polls registered grounding sources
│   ├── delta_classifier.py       # Significance gate (heuristic + LLM)
│   └── security/
│       └── gates.py              # PBKDF2 passphrase + HMAC challenge
│
├── memory/
│   ├── session.py                # Resumable session state
│   ├── longterm.py               # Persistent facts, preferences, journal
│   └── patterns.py               # Weekly behavioral pattern observations
│
└── initiation/
    ├── engine.py                 # "Nova speaks first" engine — silence-respecting
    ├── selectors.py              # Pool selection
    ├── memory_interface.py       # Per-user fact storage for contextual questions
    ├── contextual.py             # LLM-generated questions anchored to known facts
    ├── config/initiation_config.json
    └── pools/
        ├── idle.json             # ← Empty. Add your own light questions.
        └── reflective.json       # ← Empty. Add your own deeper prompts.
```

---

## Core ideas

**The voice loop is silent by default.** `pipeline/autonomy.py` has the canonical statement:

> Nova speaks unprompted only when CURIOSITY, DISCOVERY, or INTELLIGENCE fires. NULL is the default. Silence is valued.

Boundaries: 20-minute minimum gap between unprompted utterances; deep-work suppression; night silence (1 AM–6 AM); 10-minute post-interaction cooldown.

**The Witness never writes.** `pipeline/emotion_witness.py` watches `emotional_state.py` over time, samples activations every 5 seconds, and emits structured pattern observations (`sustained_alert`, `oscillation`, `flatline`, `rising`, `deepening`). It is **read-only** — if the witness could modify state, Nova's self-observation would change what she's observing.

**Three layers of affect.** A continuous activation blend (`emotional_state.py`) drives color and voice profile. A discrete register (`emotion_state.py`) tracks `frustrated/focused/playful/reflective/...`. The witness sits above both as observer.

**Seven response modes.** `conversational, brief, deep, creative, socratic, devils_advocate, focus`. Switch with deliberate phrases like *"deep mode"*, *"socratic mode"*, *"devil's advocate"*, *"focus mode"*. Patterns are strict on purpose — they need to read as directives, not noun phrases.

**Two ritual states.** `pipeline/nova_rituals.py` defines `SILENCE` and `DEEP_LISTENING`. Trigger silence with *"sit with me"*, *"silence"*, *"presence only"*. Trigger deep listening with *"hold space"*, *"just listen"*, *"witness this"*. Exit with *"thank you"*. In silence she stops generating; in deep listening she holds space and only responds to direct questions.

**Presence Mode.** `pipeline/presence.py`. When the user steps away, Nova doesn't go quiet — she keeps thinking and writes those thoughts to a daily journal at `nova_data/presence_log/YYYY-MM-DD-presence.md`. When the user returns, she can briefly mention what she was on.

**Speech Gate.** `pipeline/speech_gate.py`. Every unprompted speech source asks the gate before voicing. Default policy is **deny**. Every decision is audited to `nova_data/gate_log/YYYY-MM-DD.jsonl`.

**Truthfulness directive.** From the system prompt: *"You DO NOT make up names, appointments, emails, attachments, or any other plausible-sounding content. Ever. The single worst failure mode is fabricating a plausible answer when asked about specific data."*

---

## Optional HUD

Nova hosts a WebSocket bridge on `ws://127.0.0.1:8765` (loopback only). Connect a desktop UI to it to see live state, transcripts, emotion snapshots, etc. The protocol is described at the top of `nova_websocket.py`.

The repository ships an `electron/` folder containing a minimal orb UI from a prior consumer-app prototype. **It is not wired up to the Python pipeline** — it's a standalone Electron-only app that talks to the Anthropic API directly. Ignore it, replace it, or remove it depending on your direction.

---

## Extending

**Add a curiosity source.** `pipeline.delta_detector.register_source(name, snapshot_fn, diff_fn)` — provide a callable that returns a current snapshot dict, and one that diffs prev/cur into delta records. The curiosity engine handles rate limits and gates from there.

**Tune the curiosity classifier.** `pipeline.delta_classifier.register_heuristic(source, fn)` — return a verdict dict or None to defer to the LLM.

**Lift the speech gate.** Edit `ALLOW_SOURCES` in `pipeline/speech_gate.py` (or call `speech_gate.allow("source_name")` at runtime) to permit unprompted output from a given source.

**Add initiation questions.** Drop entries into `initiation/pools/idle.json` and `initiation/pools/reflective.json`. Format: `{"id": "idle_001", "text": "What's something you're enjoying lately?", "weight": "light"}`.

---

## License

To be added. Treat as all-rights-reserved until then.

---

*Infinitum Cor LLC*
