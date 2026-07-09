# setup_wizard.py
# ═══════════════════════════════════════════════════════════════
# First-time setup — builds your .env interactively.
#
# Run by install.sh / install.ps1, or directly:
#   python setup_wizard.py
#
# Asks only for what Nova actually needs; everything optional can be
# skipped with Enter and added to .env later. Never overwrites an
# existing key without asking.
# ═══════════════════════════════════════════════════════════════

import os
import sys

ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


def _read_env() -> dict:
    data = {}
    if os.path.exists(ENV_PATH):
        for line in open(ENV_PATH, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                data[k.strip()] = v.strip()
    return data


def _write_env(data: dict):
    lines = [
        "# Nova configuration — created by setup_wizard.py",
        "# Everything here stays on your machine.",
        "",
    ]
    for k, v in data.items():
        lines.append(f"{k}={v}")
    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _ask(prompt: str, current: str = "", secret: bool = False) -> str:
    shown = " [set — Enter keeps it]" if current else ""
    try:
        if secret and current:
            val = input(f"{prompt}{shown}: ").strip()
        else:
            val = input(f"{prompt}{shown}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nSetup cancelled — run setup_wizard.py again anytime.")
        sys.exit(1)
    return val or current



def _ensure_ollama(model: str):
    """Check the local Ollama install and offer to pull the model."""
    import shutil
    import subprocess
    if not shutil.which("ollama"):
        print("\n   Ollama is not installed yet. Install it from:")
        print("     https://ollama.com/download")
        print("   (Linux one-liner:  curl -fsSL https://ollama.com/install.sh | sh)")
        print(f"   Then run:  ollama pull {model}")
        return
    print(f"   Ollama found — making sure '{model}' is downloaded")
    print("   (first download is a few GB; Enter to pull now, 's' to skip)")
    try:
        skip = input("   Pull model? [Enter=yes / s=skip]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return
    if skip.startswith("s"):
        print(f"   Skipped. Later, run:  ollama pull {model}")
        return
    try:
        subprocess.run(["ollama", "pull", model], check=True)
        print(f"   ✓ {model} ready.")
    except Exception as e:
        print(f"   Pull failed ({e}). If the Ollama service isn't running,")
        print(f"   start it (ollama serve) and run:  ollama pull {model}")


def _pick_microphone(env: dict):
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        inputs = [(i, d) for i, d in enumerate(devices)
                  if d.get("max_input_channels", 0) > 0]
        if not inputs:
            print("  No input devices found — Nova will use the system default.")
            return
        print("\n  Microphones found:")
        for i, d in inputs:
            print(f"    [{i}] {d['name']}")
        choice = _ask("  Device number (Enter = system default)",
                      env.get("NOVA_AUDIO_DEVICE", ""))
        if choice.strip().isdigit():
            env["NOVA_AUDIO_DEVICE"] = choice.strip()
    except Exception as e:
        print(f"  (Could not list microphones: {e} — system default will be used.)")


def main():
    print("═" * 60)
    print("  NOVA — first-time setup")
    print("═" * 60)
    print("Free by default — no keys required. Everything optional.\n")

    env = _read_env()

    # Her mind — free by default.
    print("1. Her mind")
    print("   [1] Local & free (Ollama) — nothing you say ever leaves this")
    print("       machine, and it costs nothing. (default)")
    print("   [2] Claude API (Anthropic) — stronger reasoning; needs a paid key.")
    choice = _ask("   Choice", env.get("LLM_PROVIDER", "") and
                  ("2" if env.get("LLM_PROVIDER") == "anthropic" else "1")) or "1"
    if choice.strip() == "2":
        env["LLM_PROVIDER"] = "anthropic"
        print("   Get a key at: https://console.anthropic.com/settings/keys")
        key = _ask("   ANTHROPIC_API_KEY", env.get("ANTHROPIC_API_KEY", ""), secret=True)
        if key:
            env["ANTHROPIC_API_KEY"] = key
        else:
            print("   No key entered — add ANTHROPIC_API_KEY to .env later.")
    else:
        env["LLM_PROVIDER"] = "ollama"
        print("\n   Model size — bigger is smarter, smaller is faster:")
        print("   [1] llama3.2   (3B — runs on most machines) (default)")
        print("   [2] llama3.1:8b (8B — better, needs ~8GB RAM/VRAM)")
        m = _ask("   Choice", "")
        env["OLLAMA_MODEL"] = "llama3.1:8b" if m.strip() == "2" else \
            (env.get("OLLAMA_MODEL") or "llama3.2")
        _ensure_ollama(env["OLLAMA_MODEL"])

    # Optional: premium voice.
    print("\n2. ElevenLabs voice (optional — premium TTS; free Edge-TTS otherwise)")
    el = _ask("   ELEVENLABS_API_KEY (Enter to skip)", env.get("ELEVENLABS_API_KEY", ""), secret=True)
    if el:
        env["ELEVENLABS_API_KEY"] = el
        env["ELEVENLABS_VOICE_ID"] = _ask("   ELEVENLABS_VOICE_ID",
                                          env.get("ELEVENLABS_VOICE_ID", ""))
        env["TTS_PROVIDER"] = "elevenlabs"
    else:
        env.setdefault("TTS_PROVIDER", "edge")

    # Optional: hands-free wake word.
    print("\n3. Picovoice wake word (optional — hands-free 'computer' wake;")
    print("   without it you press Enter to wake her)")
    print("   Free key at: https://console.picovoice.ai/")
    pv = _ask("   PICOVOICE_ACCESS_KEY (Enter to skip)",
              env.get("PICOVOICE_ACCESS_KEY", ""), secret=True)
    if pv:
        env["PICOVOICE_ACCESS_KEY"] = pv

    # Timezone.
    print("\n4. Timezone (IANA name, e.g. America/New_York, Europe/Berlin)")
    env["NOVA_TIMEZONE"] = _ask("   NOVA_TIMEZONE",
                                env.get("NOVA_TIMEZONE", "") or "America/Chicago")

    # Microphone.
    print("\n5. Microphone")
    _pick_microphone(env)

    _write_env(env)
    print(f"\nSaved → {ENV_PATH}")
    print("Setup complete. She meets you on first run — she'll ask your name.")


if __name__ == "__main__":
    main()
