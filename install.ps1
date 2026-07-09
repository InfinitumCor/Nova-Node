# ═══════════════════════════════════════════════════════════════
# Nova — one-stop install (Windows)
#
#   powershell -ExecutionPolicy Bypass -File install.ps1
#
# Creates a virtual environment, installs every dependency, checks
# for ffmpeg, then walks you through first-time setup and verifies
# the result. When it finishes, .\nova.ps1 starts her.
# ═══════════════════════════════════════════════════════════════
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Say($t)  { Write-Host "`n$t" -ForegroundColor Cyan }
function Ok($t)   { Write-Host "  + $t" -ForegroundColor Green }
function Warn($t) { Write-Host "  ! $t" -ForegroundColor Yellow }

Say "Nova install - checking your system"

# -- Python 3.10+ --
$py = $null
foreach ($c in @("py -3.12", "py -3.11", "py -3.10", "py -3", "python")) {
    try {
        $v = Invoke-Expression "$c -c `"import sys; print(sys.version_info >= (3,10))`"" 2>$null
        if ($v -match "True") { $py = $c; break }
    } catch {}
}
if (-not $py) { Write-Host "  x Python 3.10+ not found. Install from python.org, then re-run." -ForegroundColor Red; exit 1 }
Ok "Python found ($py)"

# -- ffmpeg --
if (Get-Command ffmpeg -ErrorAction SilentlyContinue) {
    Ok "ffmpeg present"
} else {
    Warn "ffmpeg not found - Whisper transcription needs it."
    Write-Host "    Install with:  winget install Gyan.FFmpeg   (then reopen this terminal)"
    $yn = Read-Host "  Continue anyway? [y/N]"
    if ($yn -notmatch "^[Yy]") { exit 1 }
}

# -- Ollama (her default mind - local and free) --
if (Get-Command ollama -ErrorAction SilentlyContinue) {
    Ok "Ollama present"
} else {
    Warn "Ollama not found - it's her default mind (local, free, private)."
    Write-Host "    Skip this if you plan to use the Claude API instead."
    $yn = Read-Host "  Install Ollama now via winget? [Y/n]"
    if ($yn -notmatch "^[Nn]") {
        try { winget install -e --id Ollama.Ollama } catch { Warn "winget failed - install manually from https://ollama.com/download" }
    }
}

# -- Virtual environment + dependencies --
Say "Installing Nova's environment (this downloads Whisper + friends - a few minutes)"
if (-not (Test-Path "venv")) { Invoke-Expression "$py -m venv venv" }
.\venv\Scripts\python.exe -m pip install --upgrade pip -q
.\venv\Scripts\python.exe -m pip install -r requirements.txt
Ok "Dependencies installed"

# -- First-run setup --
Say "First-time setup"
.\venv\Scripts\python.exe setup_wizard.py

# -- Verify --
Say "Verifying the install"
.\venv\Scripts\python.exe doctor.py

# -- Run script --
@"
Set-Location `$PSScriptRoot
& .\venv\Scripts\python.exe nova.py @args
"@ | Out-File -FilePath "nova.ps1" -Encoding utf8

Say "Done. Start her with:  .\nova.ps1"
