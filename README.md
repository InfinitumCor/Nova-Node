# Nova

> Not an assistant. A presence.

Nova is a local voice companion built around a single principle: **silence is the default**. She doesn't speak unless spoken to — and she can tell the difference. She judges whether words were meant for her before answering, stays quiet while you dictate a number to someone on the phone, and always answers when you say her name.

She ships knowing no one. The first time she runs, she introduces herself and asks what to call you. From that moment, her memory of you — your name, what you ask her to remember, her own emotional weather — lives in a folder on your machine and nowhere else.

— Infinitum Cor LLC

---

## What she is

```
Wake word   →   Speech-to-text   →   LLM              →   Text-to-speech
(Porcupine      (local Whisper)      (local Ollama,        (Edge-TTS free,
 or ENTER)                            free — default;       ElevenLabs optional)
                                      Claude API optional)
```

**Completely free by default.** Her mind is a local model (Ollama) — no API key, no subscription, no cost, ever. And with the default setup, *nothing you say leaves your machine at all*: not audio, not text. The Claude API is there as an optional upgrade for stronger reasoning, but she never requires it.

**What makes her different from a voice loop:**

- **Addressed-to-me judgment** — she distinguishes talking *to* her from talking *near* her. Dictation, third-party conversation, and muttering at your screen earn silence; questions, requests, and her name always reach her. Silence must be earned by evidence — when uncertain, she answers.
- **She never goes silent on you** — if the model errors or returns nothing, she retries, and failing that she *says so* ("I lost that thought mid-stride — say it again?"). A companion that answers with silence is broken; every quiet moment she chooses is logged and auditable in `nova_data/silent_drops.jsonl`.
- **A conversation window** — after she answers, the mic stays open briefly. Follow-ups don't need the wake word; silence hands the room back.
- **An emotional model that observes itself** — a continuous six-state engine (present / warm / curious / still / alert / dim) with real decay, an eleven-register carry-forward, and a witness layer that watches her own patterns and folds what it sees back into how she speaks.
- **Rituals** — "sit with me" makes her a silent presence; "just listen" makes her a witness. Some moments don't want a response.
- **Response modes** — conversational, brief, deep, creative, socratic, devil's advocate, focus. Switch mid-conversation by asking.
- **Boundaried autonomy** — she may speak unprompted, but only through a default-deny gate: never during deep work, never at night, never twice in a row. Every decision is audited.
- **Memory that survives** — session resume across restarts, long-term facts ("remember that…"), preferences, and a journal — all plain JSON in `nova_data/`, written atomically so a crash can't corrupt them.

## Install — one command

**Linux / macOS**

```bash
git clone <this repo> && cd Nova-Node
./install.sh
```

**Windows (PowerShell)**

```powershell
git clone <this repo>; cd Nova-Node
powershell -ExecutionPolicy Bypass -File install.ps1
```

The installer creates a virtual environment, installs every dependency (including Ollama, her free local mind, with your consent), checks the pieces Python can't install (ffmpeg, audio backend), walks you through setup — no keys required, everything optional — and verifies the result. Then:

```bash
./nova.sh        # Linux / macOS
.\nova.ps1       # Windows
```

She'll introduce herself.

**Something off?** `python doctor.py` checks every component and says plainly what's missing and how to fix it.

## Keys — none required

| Key | Needed? | What it does |
|---|---|---|
| *(nothing)* | — | Default setup is fully local and free: Ollama mind, Whisper ears, Edge-TTS voice |
| `ANTHROPIC_API_KEY` | Optional | Upgrade her mind to Claude — [console.anthropic.com](https://console.anthropic.com/settings/keys) |
| `ELEVENLABS_API_KEY` + `VOICE_ID` | Optional | Premium voice; free Edge-TTS otherwise |
| `PICOVOICE_ACCESS_KEY` | Optional | Hands-free wake word (free tier); press-Enter wake otherwise — [console.picovoice.ai](https://console.picovoice.ai/) |

Re-run `python setup_wizard.py` anytime to change these.

## Configuration

Every knob lives in [config.py](config.py) with its documentation inline: VAD sensitivity and silence windows, echo rejection, the addressed-judgment momentum window, the follow-up window, response modes, emotional engine toggles, autonomy boundaries, timezone.

## Build her a face

Nova runs headless, but she broadcasts everything a UI needs on a local WebSocket (`ws://127.0.0.1:8765`): state changes (`idle / listening / thinking / speaking`), transcripts of both sides, and she accepts typed input the same way. The protocol is documented in [nova_websocket.py](nova_websocket.py). Bring your own presence — a terminal bar, an orb, a full HUD. Hers to inhabit, yours to design.

## Privacy

- **Default setup: nothing leaves your machine.** Voice is transcribed locally (Whisper), her mind runs locally (Ollama), her memory lives locally (`nova_data/`)
- If you opt into the Claude API: only the transcribed text of turns *addressed to her* is sent — never audio, never ambient speech
- Turns *not* addressed to her: dropped locally and logged locally, never sent anywhere
- Memory, session, emotional state, logs: plain JSON under `nova_data/`, yours to read or delete

## What's new in v4

- **Completely free by default** — local Ollama mind; the Claude API is now an optional upgrade, not a requirement
- Addressed-to-me judgment (silence must be earned by evidence)
- First meeting — she ships knowing no one and asks your name
- Never-go-silent guarantee with honest recovery lines
- Silent-drop diagnostics (`nova_data/silent_drops.jsonl`)
- Conversation follow-up window (no wake word for follow-ups)
- Echo rejection + Whisper-hallucination filtering actually enforced
- Long-term memory now injected into her prompt (remember/forget is real) and written atomically
- API errors no longer crash the conversation loop
- One-stop install: `install.sh` / `install.ps1` + `setup_wizard.py` + `doctor.py`
- Removed the legacy Electron shell (browser-side API calls were unsafe); the WebSocket bridge replaces it

## License

[MIT](LICENSE) — she's yours. Use her, change her, build on her, ship her. © 2026 Infinitum Cor LLC.
