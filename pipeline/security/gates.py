# pipeline/security/gates.py
# ═══════════════════════════════════════════════════════════════
# Sensitive-action gates — passphrase challenge layer.
#
# Pattern:
#   - register_passphrase(plaintext)  → derives & stores a hash
#   - has_passphrase()                → bool
#   - challenge(action_label)         → returns a Challenge object
#   - verify(challenge_id, answer)    → True/False, marks attempt
#   - is_action_sensitive(action)     → consults policy
#
# Storage: passphrase hash + salt live at config.GATE_SECRETS_PATH.
# Never logs the plaintext. Always uses constant-time compare.
#
# Public release ships with an EMPTY SENSITIVE_ACTIONS policy. Register
# the actions you want to gate via the `register_sensitive_action()`
# helper, or by editing the dict directly.
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from config import config

GATE_SECRETS = Path(config.GATE_SECRETS_PATH)
GATE_LOG = Path(config.GATE_LOG_PATH)

_PBKDF2_ITERATIONS = 200_000
_SALT_BYTES = 16
_CHALLENGE_TTL_SECONDS = 90


# ─────────────────────────────────────────────────────────────
# Sensitive action policy
# ─────────────────────────────────────────────────────────────

# Each action maps to a severity:
#   - critical: gate ALWAYS required; failure logs an alert
#   - elevated: gate required unless explicitly bypassed
#   - normal:   gate not required
#
# Public ships empty — register what matters to YOUR build.
SENSITIVE_ACTIONS: dict[str, str] = {}


def register_sensitive_action(action: str, severity: str = "elevated") -> None:
    """Register an action with a severity. Idempotent."""
    if severity not in ("critical", "elevated", "normal"):
        raise ValueError(f"Unknown severity: {severity}")
    SENSITIVE_ACTIONS[action] = severity


def is_action_sensitive(action: str) -> str:
    """Return the severity level of an action, or 'normal' if not listed."""
    return SENSITIVE_ACTIONS.get(action, "normal")


# ─────────────────────────────────────────────────────────────
# Passphrase storage (PBKDF2-HMAC-SHA256)
# ─────────────────────────────────────────────────────────────

def _hash_passphrase(plaintext: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256", plaintext.encode("utf-8"), salt, _PBKDF2_ITERATIONS
    )


def has_passphrase() -> bool:
    return GATE_SECRETS.exists()


def register_passphrase(plaintext: str) -> None:
    """
    Store a new passphrase. Overwrites any existing one.
    Plaintext is never written to disk or logged.
    """
    if not plaintext or len(plaintext) < 4:
        raise ValueError("Passphrase must be at least 4 characters.")
    GATE_SECRETS.parent.mkdir(parents=True, exist_ok=True)
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = _hash_passphrase(plaintext, salt)
    payload = {
        "version": 1,
        "salt_hex": salt.hex(),
        "digest_hex": digest.hex(),
        "iterations": _PBKDF2_ITERATIONS,
        "issued": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    GATE_SECRETS.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _verify_against_stored(plaintext: str) -> bool:
    if not GATE_SECRETS.exists():
        return False
    try:
        data = json.loads(GATE_SECRETS.read_text(encoding="utf-8"))
        salt = bytes.fromhex(data["salt_hex"])
        expected = bytes.fromhex(data["digest_hex"])
    except Exception:
        return False
    presented = _hash_passphrase(plaintext, salt)
    return hmac.compare_digest(presented, expected)


# ─────────────────────────────────────────────────────────────
# Challenge / response
# ─────────────────────────────────────────────────────────────

@dataclass
class Challenge:
    id: str
    action: str
    severity: str
    issued_ts: float
    expired: bool = False
    consumed: bool = False
    result: Optional[bool] = None
    metadata: dict = field(default_factory=dict)

    @property
    def is_alive(self) -> bool:
        return (
            not self.expired
            and not self.consumed
            and (time.time() - self.issued_ts) < _CHALLENGE_TTL_SECONDS
        )


_pending: dict[str, Challenge] = {}


def challenge(action: str, metadata: Optional[dict] = None) -> Challenge:
    """
    Open a challenge for `action`. Returns a Challenge object.
    Caller is responsible for prompting the user (Nova will say:
    "Authorize by saying [your passphrase].") and then calling
    verify(challenge_id, answer).
    """
    cid = secrets.token_urlsafe(8)
    sev = is_action_sensitive(action)
    ch = Challenge(
        id=cid,
        action=action,
        severity=sev,
        issued_ts=time.time(),
        metadata=metadata or {},
    )
    _pending[cid] = ch
    return ch


def verify(challenge_id: str, answer: str) -> bool:
    """Check the answer against the stored passphrase. Marks the challenge consumed."""
    ch = _pending.get(challenge_id)
    if not ch:
        return False
    if not ch.is_alive:
        ch.expired = True
        return False
    ok = _verify_against_stored(answer or "")
    ch.consumed = True
    ch.result = ok
    _log_attempt(ch)
    return ok


def _log_attempt(ch: Challenge) -> None:
    """Append a single line to the gate log."""
    GATE_LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        "challenge_id": ch.id,
        "action": ch.action,
        "severity": ch.severity,
        "result": "pass" if ch.result else "fail",
        "metadata": ch.metadata,
    }
    try:
        with open(GATE_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except Exception as e:
        print(f"[Gates] log write failed: {e}")


# ─────────────────────────────────────────────────────────────
# Convenience for callers
# ─────────────────────────────────────────────────────────────

def gate_required_for(action: str) -> bool:
    """Critical and elevated actions both require a gate by default."""
    sev = is_action_sensitive(action)
    return sev in ("critical", "elevated")


def stats_24h() -> dict:
    """Read the gate log and return a 24h summary."""
    if not GATE_LOG.exists():
        return {"total": 0, "passed": 0, "failed": 0}
    cutoff = datetime.datetime.now() - datetime.timedelta(hours=24)
    total = passed = failed = 0
    try:
        with open(GATE_LOG, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    ts = datetime.datetime.fromisoformat(entry["ts"])
                    if ts < cutoff:
                        continue
                    total += 1
                    if entry.get("result") == "pass":
                        passed += 1
                    else:
                        failed += 1
                except Exception:
                    continue
    except Exception:
        pass
    return {"total": total, "passed": passed, "failed": failed}
