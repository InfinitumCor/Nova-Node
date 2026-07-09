#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
# Nova — one-stop install (Linux / macOS)
#
#   ./install.sh
#
# Creates a virtual environment, installs every dependency, checks
# the system pieces Python can't install for you (ffmpeg, an audio
# backend), then walks you through first-time setup and verifies
# the result. When it finishes, `./nova.sh` starts her.
# ═══════════════════════════════════════════════════════════════
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

say()  { printf '\n\033[1;36m%s\033[0m\n' "$1"; }
ok()   { printf '  \033[1;32m✓\033[0m %s\n' "$1"; }
warn() { printf '  \033[1;33m!\033[0m %s\n' "$1"; }
die()  { printf '  \033[1;31m✗ %s\033[0m\n' "$1"; exit 1; }

say "Nova install — checking your system"

# ── Python 3.10+ ──
PY=""
for c in python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1; then
    if "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'; then
      PY="$c"; break
    fi
  fi
done
[ -n "$PY" ] || die "Python 3.10+ not found. Install it, then re-run."
ok "Python: $($PY --version 2>&1)"

# ── ffmpeg (Whisper + audio decoding need it) ──
if command -v ffmpeg >/dev/null 2>&1; then
  ok "ffmpeg present"
else
  warn "ffmpeg not found — Whisper transcription needs it."
  if command -v apt-get >/dev/null 2>&1; then
    echo    "    Install with:  sudo apt-get install -y ffmpeg"
  elif command -v brew >/dev/null 2>&1; then
    echo    "    Install with:  brew install ffmpeg"
  fi
  read -rp "  Continue anyway? [y/N] " yn
  [[ "${yn:-n}" =~ ^[Yy] ]] || exit 1
fi

# ── PortAudio (sounddevice backend on Linux) ──
if [ "$(uname -s)" = "Linux" ] && ! ldconfig -p 2>/dev/null | grep -q libportaudio; then
  warn "libportaudio not found — the microphone won't open without it."
  echo "    Install with:  sudo apt-get install -y libportaudio2"
  read -rp "  Continue anyway? [y/N] " yn
  [[ "${yn:-n}" =~ ^[Yy] ]] || exit 1
fi

# ── Ollama (her default mind — local and free) ──
if command -v ollama >/dev/null 2>&1; then
  ok "Ollama present ($(ollama --version 2>/dev/null | head -1))"
else
  warn "Ollama not found — it's her default mind (local, free, private)."
  echo "    You can skip this if you plan to use the Claude API instead."
  read -rp "  Install Ollama now via the official script? [Y/n] " yn
  if [[ ! "${yn:-y}" =~ ^[Nn] ]]; then
    curl -fsSL https://ollama.com/install.sh | sh || warn "Ollama install failed — install manually from https://ollama.com/download"
  fi
fi

# ── Virtual environment + dependencies ──
say "Installing Nova's environment (this downloads Whisper + friends — a few minutes)"
[ -d venv ] || "$PY" -m venv venv
./venv/bin/pip install --upgrade pip -q
./venv/bin/pip install -r requirements.txt
ok "Dependencies installed"

# ── First-run setup (interactive .env builder) ──
say "First-time setup"
./venv/bin/python setup_wizard.py

# ── Verify ──
say "Verifying the install"
./venv/bin/python doctor.py || warn "Doctor found issues above — Nova may still run degraded."

# ── Run script ──
cat > nova.sh <<'RUN'
#!/usr/bin/env bash
cd "$(dirname "${BASH_SOURCE[0]}")"
exec ./venv/bin/python nova.py "$@"
RUN
chmod +x nova.sh

say "Done. Start her with:  ./nova.sh"
