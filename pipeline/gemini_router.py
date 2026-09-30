"""Gemini model router — quota-aware, day-reset, persisted to .gemini_quota.json.

Real free-tier limits scraped from the ExamCrackerAI project dashboard
(28-day window, September 2026):

  TIER 2 — Flash Lite (RPM 15, RPD 500 each)
    gemini-3.5-flash-lite  <- primary drafter (script / SEO)
    gemini-3.1-flash-lite  <- cross-model fact-checker / polish

  TIER 3 — Gemma 4 (RPM 30, RPD 14,400 each — workhorse)
    gemma-4-26b, gemma-4-31b

Strategy
--------
* Two Flash-Lite models are used intentionally: gemini-3.5 drafts the script
  and gemini-3.1 fact-checks and polishes it.  Two different model weights
  rarely make the same factual mistake.
* Thinking levels per call type:
    - SCRIPT_GEN  -> thinking_budget=8192  (quality is paramount)
    - FACT_CHECK  -> thinking_budget=8192  (accuracy matters)
    - POLISH      -> thinking_budget=2048  (hook + pacing review)
    - SEO         -> thinking_budget=512   (lightweight; save tokens for scripts)
    - JSON_REPAIR -> thinking_budget=0     (mechanical; no thinking needed)
* SCRIPT_GEN uses response_schema to hard-enforce <=5 scenes + field types,
  eliminating most structural repair calls ("6 scenes" rejections are gone).
* exclude_model parameter lets the caller force the OTHER Flash-Lite for
  cross-model checking:
      router.generate(prompt, CallType.FACT_CHECK,
                      exclude_model="gemini-3.5-flash-lite")
* Within each tier models are tried in order; a model is skipped if:
    - its daily counter has hit RPD, OR
    - it is in the session blacklist (non-retriable error returned)
* On a 429 with retry_delay <= MAX_RETRY_WAIT_SECONDS the same model is
  retried once after sleeping.  Longer delays -> move to the next model.
* RPD counters are persisted in .gemini_quota.json so multiple pipeline
  runs on the same calendar day don't start from zero.
  The file is reset automatically when the UTC date changes.

Usage
-----
    from .gemini_router import GeminiRouter, CallType

    router = GeminiRouter(api_key=settings.gemini_api_key)
    text = router.generate(prompt, call_type=CallType.SCRIPT_GEN)
    # Cross-model fact-check (excludes the drafter so a different model checks):
    text = router.generate(prompt, call_type=CallType.FACT_CHECK,
                           exclude_model="gemini-3.5-flash-lite")
"""
from __future__ import annotations

import json
import time
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import google.generativeai as genai

from .config import ROOT

# --- Quota state persistence --------------------------------------------------
_STATE_PATH = ROOT / ".gemini_quota.json"
MAX_RETRY_WAIT_SECONDS: int = 25


# --- Model catalogue ----------------------------------------------------------
@dataclass
class _ModelSpec:
    name: str          # API identifier
    rpm: int           # requests per minute (free tier)
    rpd: int           # requests per day (free tier)
    tier: int          # 2 = Flash-Lite, 3 = Gemma


# Gemini Flash Lite -- 500 RPD each, 15 RPM
_FLASH_LITE = [
    _ModelSpec("gemini-3.5-flash-lite", rpm=15, rpd=500, tier=2),
    _ModelSpec("gemini-3.1-flash-lite", rpm=15, rpd=500, tier=2),
]

# Gemma 4 -- 14,400 RPD each, 30 RPM
_GEMMA = [
    _ModelSpec("gemma-4-26b", rpm=30, rpd=14_400, tier=3),
    _ModelSpec("gemma-4-31b", rpm=30, rpd=14_400, tier=3),
]

_ALL_MODELS: dict[str, _ModelSpec] = {
    m.name: m for m in (_FLASH_LITE + _GEMMA)
}


# --- Call types and preferred model ordering ----------------------------------
class CallType(str, Enum):
    SCRIPT_GEN  = "script_gen"    # Main video script -- schema-constrained, high thinking
    FACT_CHECK  = "fact_check"    # Cross-model fact-verification -- high thinking
    SEO         = "seo"           # Title/description/tags -- low thinking
    JSON_REPAIR = "json_repair"   # Fix malformed JSON -- no thinking
    POLISH      = "polish"        # Hook + pacing polish pass -- medium thinking


# Thinking token budget per call type.
# 0 = no thinking (fastest), 512 = low, 2048 = medium, 8192 = high.
_THINKING_BUDGET: dict[CallType, int] = {
    CallType.SCRIPT_GEN:  8192,
    CallType.FACT_CHECK:  8192,
    CallType.POLISH:      2048,
    CallType.SEO:          512,
    CallType.JSON_REPAIR:    0,
}

# Ordered list of model names per call type.
# FACT_CHECK and POLISH deliberately start with 3.1 -- different from the
# 3.5 drafter -- cross-model checking is the whole point.
_CALL_ORDER: dict[CallType, list[str]] = {
    CallType.SCRIPT_GEN: [
        "gemini-3.5-flash-lite",   # primary drafter
        "gemini-3.1-flash-lite",
        "gemma-4-26b",
        "gemma-4-31b",
    ],
    CallType.FACT_CHECK: [
        # Cross-model checker -- caller passes exclude_model="gemini-3.5-flash-lite"
        "gemini-3.1-flash-lite",
        "gemma-4-26b",
        "gemma-4-31b",
        "gemini-3.5-flash-lite",   # last resort only
    ],
    CallType.POLISH: [
        "gemini-3.1-flash-lite",   # cross-model also for polish
        "gemini-3.5-flash-lite",
        "gemma-4-26b",
        "gemma-4-31b",
    ],
    CallType.SEO: [
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
        "gemma-4-26b",
        "gemma-4-31b",
    ],
    CallType.JSON_REPAIR: [
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
        "gemma-4-26b",
        "gemma-4-31b",
    ],
}


# --- JSON response schema for SCRIPT_GEN -------------------------------------
# V6 schema: exactly six teaching scenes and explicit thumbnail fields.
# This prevents the old A/B/countdown challenge structure from re-entering via schema output.
_SCRIPT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "hook": {"type": "string"},
        "description": {"type": "string"},
        "pinned_comment": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "thumbnail_text": {"type": "string"},
        "thumbnail_subline": {"type": "string"},
        "thumbnail_visual_prompt": {"type": "string"},
        "scenes": {
            "type": "array",
            "minItems": 6,
            "maxItems": 6,
            "items": {
                "type": "object",
                "properties": {
                    "action_type": {"type": "string"},
                    "action_payload": {"type": "string"},
                    "narration": {"type": "string"},
                    "tts_text": {"type": "string"},
                    "image_prompt": {"type": "string"},
                    "on_screen_text": {"type": "string"},
                    "card_points": {"type": "array", "items": {"type": "string"}},
                    "motion_type": {"type": "string"},
                    "camera_motion": {"type": "string"},
                    "sfx_cue": {"type": "string"},
                },
                "required": [
                    "action_type", "action_payload", "narration", "tts_text",
                    "image_prompt", "on_screen_text", "card_points",
                    "motion_type", "camera_motion", "sfx_cue",
                ],
            },
        },
    },
    "required": [
        "title", "hook", "description", "pinned_comment", "tags",
        "thumbnail_text", "thumbnail_subline", "thumbnail_visual_prompt", "scenes",
    ],
}


# --- Persisted quota state ----------------------------------------------------
@dataclass
class _QuotaState:
    day: str                          # ISO date string (UTC)
    used: dict[str, int] = field(default_factory=dict)  # model -> calls today

    def calls_today(self, model: str) -> int:
        return self.used.get(model, 0)

    def record(self, model: str) -> None:
        self.used[model] = self.used.get(model, 0) + 1

    def exhausted(self, model: str) -> bool:
        spec = _ALL_MODELS.get(model)
        if spec is None:
            return False
        return self.calls_today(model) >= spec.rpd


def _today_utc() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _load_state() -> _QuotaState:
    today = _today_utc()
    if _STATE_PATH.exists():
        try:
            data = json.loads(_STATE_PATH.read_text())
            if data.get("day") == today:
                return _QuotaState(day=today, used=data.get("used", {}))
        except Exception:
            pass
    return _QuotaState(day=today)


def _save_state(state: _QuotaState) -> None:
    try:
        _STATE_PATH.write_text(json.dumps(asdict(state), indent=2))
    except Exception as exc:
        print(f"[router] WARNING: could not persist quota state: {exc}")


# --- Helpers ------------------------------------------------------------------
def _parse_retry_delay(exc: Exception) -> float | None:
    msg = str(exc)
    m = re.search(r"retry_delay\s*\{\s*seconds:\s*(\d+)", msg)
    if m:
        return float(m.group(1))
    m = re.search(r"retry in\s+([\d.]+)s", msg, re.I)
    if m:
        return float(m.group(1))
    return None


def _is_daily_quota_error(exc: Exception) -> bool:
    """Return True only for per-day exhaustion, never for short-window RPM spikes."""
    msg = str(exc)
    if "retry_delay" in msg or re.search(r"retry in\s+[\d.]+s", msg, re.I):
        return False
    return (
        "GenerateRequestsPerDayPerProjectPerModel" in msg
        or ("quota" in msg.lower() and "day" in msg.lower())
    )


# --- Router -------------------------------------------------------------------
class GeminiRouter:
    """Quota-aware Gemini router with thinking levels and schema-constrained output.

    One instance per pipeline run is fine -- it shares the persisted state file
    between runs on the same calendar day.
    """

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._state = _load_state()
        self._session_blacklist: set[str] = set()
        genai.configure(api_key=api_key)

    # -- Public API ------------------------------------------------------------
    def generate(
        self,
        prompt: str,
        call_type: CallType = CallType.SCRIPT_GEN,
        exclude_model: str | None = None,
        use_schema: bool = True,
    ) -> str:
        """Generate text, routing through models by call type and quota.

        Args:
            prompt:        The prompt string.
            call_type:     Determines model order and thinking level.
            exclude_model: Skip this specific model name.  Pass the drafter's
                           name to force the OTHER Flash-Lite for fact-checking.
            use_schema:    Apply response_schema for SCRIPT_GEN calls (default True).
                           Set False during JSON_REPAIR where schema may be too strict.
        """
        order = _CALL_ORDER[call_type]
        last_exc: Exception | None = None

        for model_name in order:
            if exclude_model and model_name == exclude_model:
                print(f"[router] {model_name} excluded — cross-model check")
                continue
            if model_name in self._session_blacklist:
                print(f"[router] {model_name} skipped — session blacklist")
                continue
            if self._state.exhausted(model_name):
                spec = _ALL_MODELS[model_name]
                print(f"[router] {model_name} skipped — {spec.rpd} RPD exhausted today")
                continue

            retry_attempted = False
            while True:
                try:
                    text = self._call(model_name, prompt, call_type, use_schema)
                    self._state.record(model_name)
                    _save_state(self._state)
                    spec = _ALL_MODELS[model_name]
                    remaining = spec.rpd - self._state.calls_today(model_name)
                    bgt = _THINKING_BUDGET[call_type]
                    print(
                        f"[router] {model_name} OK ({call_type.value}) "
                        f"thinking={bgt}tok — {remaining} RPD left today"
                    )
                    return text

                except Exception as exc:
                    is_429 = "429" in str(exc) or "quota" in str(exc).lower()

                    if is_429 and _is_daily_quota_error(exc):
                        spec = _ALL_MODELS.get(model_name)
                        if spec:
                            self._state.used[model_name] = spec.rpd
                            _save_state(self._state)
                        print(f"[router] {model_name} daily quota exhausted — skipping")
                        last_exc = exc
                        break

                    if is_429 and not retry_attempted:
                        delay = _parse_retry_delay(exc)
                        if delay is not None and delay <= MAX_RETRY_WAIT_SECONDS:
                            print(f"[router] {model_name} RPM-limited — sleeping {delay:.0f}s then retrying")
                            time.sleep(delay + 1)
                            retry_attempted = True
                            continue

                    print(f"[router] {model_name} failed ({call_type.value}): {exc}")
                    self._session_blacklist.add(model_name)
                    last_exc = exc
                    break

        raise RuntimeError(
            f"All Gemini models exhausted for {call_type.value}. Last error: {last_exc}"
        ) from last_exc

    def budget_summary(self) -> dict[str, dict]:
        """Return remaining daily budget per model — useful for logging."""
        out = {}
        for name, spec in _ALL_MODELS.items():
            used = self._state.calls_today(name)
            out[name] = {
                "tier": spec.tier,
                "rpd": spec.rpd,
                "used_today": used,
                "remaining": max(0, spec.rpd - used),
                "exhausted": self._state.exhausted(name),
                "blacklisted": name in self._session_blacklist,
            }
        return out

    # -- Private ---------------------------------------------------------------
    def _call(
        self,
        model_name: str,
        prompt: str,
        call_type: CallType,
        use_schema: bool,
    ) -> str:
        # Base config — only fields universally supported by all SDK versions.
        # thinking_config was rejected by the installed SDK → removed.
        # response_schema is attempted first; if rejected by SDK, we retry
        # without it (QA layer enforces structure post-generation instead).
        base_config: dict[str, Any] = {
            "temperature": 0.7 if call_type in (CallType.SCRIPT_GEN, CallType.POLISH) else 0.5,
            "response_mime_type": "application/json",
        }

        want_schema = call_type == CallType.SCRIPT_GEN and use_schema

        def _attempt(with_schema: bool) -> str:
            cfg = dict(base_config)
            if with_schema:
                cfg["response_schema"] = _SCRIPT_SCHEMA
            model = genai.GenerativeModel(model_name, generation_config=cfg)
            resp = model.generate_content(prompt)
            text = getattr(resp, "text", None)
            if not text:
                raise RuntimeError(f"Gemini ({model_name}) returned an empty response")
            return text

        try:
            return _attempt(with_schema=want_schema)
        except Exception as exc:
            msg = str(exc)
            if want_schema and "Unknown field" in msg:
                print(f"[router] {model_name}: response_schema rejected by SDK — retrying without schema")
                return _attempt(with_schema=False)
            raise
