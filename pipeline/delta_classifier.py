# pipeline/delta_classifier.py
# =================================================================
# Delta significance classifier for the Curiosity Engine.
#
# Takes a structured delta from pipeline.delta_detector and decides
# whether it warrants a thought, returning:
#
#   {
#     "significant": bool,
#     "reason":      str,
#     "priority":    "high" | "medium" | "low",
#   }
#
# Policy: only "high" priority deltas advance to thought generation.
# "medium" and "low" are still returned (for logging) but the curiosity
# engine ignores them.
#
# The classifier is conservative on purpose. The whole point is to drop
# autonomous-thought volume from dozens-per-day to 3–10-per-day.
#
# Public release ships with NO heuristics. Register your own per-source
# heuristic via register_heuristic(source_name, fn). Anything not handled
# by a heuristic falls through to the LLM at low temperature.
# =================================================================

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

import anthropic

from config import config

logger = logging.getLogger(__name__)


# ── Heuristic registry ────────────────────────────────────────────

_heuristics: Dict[str, Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]] = {}


def register_heuristic(source: str,
                       fn: Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]) -> None:
    """
    Register a per-source heuristic. fn receives the delta dict and
    returns a verdict dict (significant/priority/reason) or None to
    defer to the LLM.
    """
    _heuristics[source] = fn


# ── LLM fallback ──────────────────────────────────────────────────

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


_LLM_PROMPT = """You are a strict significance gate for an autonomous AI companion.

The companion only speaks unprompted when something genuinely matters.
Most changes are NOT significant enough — default to "low".

Given the change below, return a single JSON object on one line:
  {{"significant": bool, "priority": "high"|"medium"|"low", "reason": "<one short sentence>"}}

Only "high" priority will produce an unprompted message.
"high" requires a clear, important change the user would want to know about now.

CHANGE:
source: {source}
type:   {type}
detail: {detail}
"""


def _llm_classify(delta: Dict[str, Any]) -> Dict[str, Any]:
    try:
        prompt = _LLM_PROMPT.format(
            source=delta.get("source", ""),
            type=delta.get("type", ""),
            detail=str(delta.get("raw_data", ""))[:500],
        )
        resp = _get_client().messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=120,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(
            b.text for b in resp.content if getattr(b, "type", "") == "text"
        ).strip()
        # Best-effort JSON extraction
        import json, re
        m = re.search(r"\{[^{}]+\}", text)
        if m:
            return json.loads(m.group(0))
    except Exception as e:
        logger.debug(f"delta_classifier: LLM error ({e})")
    return {"significant": False, "priority": "low",
            "reason": "llm_unavailable"}


# ── Public entry point ────────────────────────────────────────────

def classify(delta: Dict[str, Any]) -> Dict[str, Any]:
    """
    Decide if a delta is significant. Returns a verdict dict.
    Tries registered heuristic first; falls back to the LLM.
    """
    source = delta.get("source")
    if source and source in _heuristics:
        try:
            verdict = _heuristics[source](delta)
            if verdict is not None:
                return verdict
        except Exception as e:
            logger.debug(f"delta_classifier: heuristic for {source} failed ({e})")

    return _llm_classify(delta)
