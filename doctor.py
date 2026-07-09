# doctor.py
# ═══════════════════════════════════════════════════════════════
# Install verification — checks every component Nova needs and says
# plainly what's healthy, what's degraded, and how to fix it.
#
#   python doctor.py
# ═══════════════════════════════════════════════════════════════

import importlib
import os
import shutil
import sys

OK, WARN, FAIL = "✓", "!", "✗"
_issues = 0


def _report(status: str, label: str, detail: str = ""):
    global _issues
    if status != OK:
        _issues += 1
    pad = f" — {detail}" if detail else ""
    print(f"  {status} {label}{pad}")


def check_python():
    v = sys.version_info
    _report(OK if v >= (3, 10) else FAIL,
            f"Python {v.major}.{v.minor}.{v.micro}",
            "" if v >= (3, 10) else "3.10+ required")


def check_packages():
    required = {
        "anthropic": "her mind (pip install anthropic)",
        "whisper": "speech-to-text (pip install openai-whisper)",
        "sounddevice": "microphone/speaker (pip install sounddevice)",
        "soundfile": "audio decoding (pip install soundfile)",
        "edge_tts": "free voice (pip install edge-tts)",
        "numpy": "audio math",
        "websockets": "the local bridge",
        "dotenv": "config loading (pip install python-dotenv)",
    }
    optional = {
        "elevenlabs": "premium voice (optional)",
        "pvporcupine": "hands-free wake word (optional)",
    }
    for mod, why in required.items():
        try:
            importlib.import_module(mod)
            _report(OK, mod)
        except Exception:
            _report(FAIL, mod, why)
    for mod, why in optional.items():
        try:
            importlib.import_module(mod)
            _report(OK, f"{mod} (optional)")
        except Exception:
            _report(WARN, f"{mod} missing", why)


def check_ffmpeg():
    _report(OK if shutil.which("ffmpeg") else FAIL, "ffmpeg",
            "" if shutil.which("ffmpeg") else
            "Whisper needs it — apt/brew/winget install ffmpeg")


def check_env():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from config import config
    except Exception as e:
        _report(FAIL, "config.py loads", str(e))
        return

    provider = (getattr(config, "LLM_PROVIDER", "ollama") or "ollama").lower()
    if provider == "anthropic":
        _report(OK if config.ANTHROPIC_API_KEY else FAIL,
                "ANTHROPIC_API_KEY",
                "" if config.ANTHROPIC_API_KEY else
                "LLM_PROVIDER=anthropic needs a key — run setup_wizard.py")
    else:
        _check_ollama(config)

    if config.ELEVENLABS_API_KEY:
        _report(OK, "ElevenLabs voice configured")
    else:
        _report(WARN, "ElevenLabs not set", "free Edge-TTS will be used")
    if config.PICOVOICE_ACCESS_KEY:
        _report(OK, "Picovoice wake word configured")
    else:
        _report(WARN, "Picovoice not set", "press-Enter wake (stub mode)")


def _check_ollama(config):
    """Her default mind: binary, server, and model all need to be there."""
    if not shutil.which("ollama"):
        _report(FAIL, "Ollama binary",
                "install from https://ollama.com/download")
        return
    _report(OK, "Ollama binary")
    try:
        import requests
        r = requests.get(f"{config.OLLAMA_URL.rstrip('/')}/api/tags", timeout=4)
        r.raise_for_status()
        models = [m.get("name", "") for m in r.json().get("models", [])]
        _report(OK, "Ollama server reachable")
        want = config.OLLAMA_MODEL
        have = any(m == want or m.startswith(want + ":") for m in models)
        _report(OK if have else FAIL,
                f"model '{want}'",
                "" if have else f"run:  ollama pull {want}")
    except Exception as e:
        _report(FAIL, "Ollama server",
                f"not reachable at {config.OLLAMA_URL} ({e}) — start it: ollama serve")


def check_microphone():
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        inputs = [d for d in devices if d.get("max_input_channels", 0) > 0]
        _report(OK if inputs else FAIL, f"microphone ({len(inputs)} input device(s))",
                "" if inputs else "no input devices visible")
    except Exception as e:
        _report(FAIL, "microphone", f"audio backend error: {e}")


def main():
    print("═" * 60)
    print("  NOVA — doctor")
    print("═" * 60)
    check_python()
    check_ffmpeg()
    check_packages()
    check_env()
    check_microphone()
    print("─" * 60)
    if _issues == 0:
        print("  All clear. Start her:  ./nova.sh  (or .\\nova.ps1)")
    else:
        print(f"  {_issues} issue(s) above. ✗ items block her; ! items degrade her.")
    return 0 if _issues == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
