"""Gemini model router — quota-aware, day-reset, persisted to .gemini_quota.json.

Real free-tier limits scraped from the ExamCrackerAI project dashboard
(28-day window, September 2026):

  TIER 1 — Flash (RPM 5-6, RPD 20 each)
    gemini-3.8-flash, gemini-3.7-flash, gemini-3.6-flash,
    gemini-3.5-flash, gemini-3-flash, gemini-2.5-flash

  TIER 2 — Flash Lite (RPM 8-15, RPD 500 each)
    gemini-3.5-flash-lite, gemini-3.1-flash-lite

  TIER 3 — Gemma 4 (RPM 30, RPD 14,400 each — the real workhorse)
    gemma-4-26b, gemma-4-31b

Strategy
--------
* Each Gemini call type is assigned a TIER ceiling:
    - SCRIPT_GEN   → Tier 1 preferred, falls to Tier 2, last resort Tier 3
    - FACT_CHECK   → Tier 3 first (Gemma is cheap & accurate for verification),
                     then Tier 2 as backup
    - SEO          → Tier 2 first (smaller prompt, saves Tier 1 for scripts),
                     then Tier 1, last Tier 3
    - JSON_REPAIR  → Tier 2, then Tier 1, then Tier 3

* Within each tier models are tried in order; a model is skipped if:
    - its daily counter has hit RPD, OR
    - it is in the session blacklist (non-retriable error returned)

* On a 429 with retry_delay ≤ MAX_RETRY_WAIT_SECONDS the same model is
  retried once after sleeping.  Longer delays → move to the next model.

* RPD counters are persisted in .gemini_quota.json so that multiple
  pipeline runs on the same calendar day don't start from zero.
  The file is reset automatically when the date changes (UTC).

Usage
-----
    from .gemini_router import GeminiRouter, CallType

    router = GeminiRouter(api_key=settings.gemini_api_key)
    text = router.generate(prompt, call_type=CallType.SCRIPT_GEN)
"""
from __future__ import annotations

import json
import time
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

import google.generativeai as genai

from .config import ROOT

# ─── Quota state persistence ──────────────────────────────────────────────────
_STATE_PATH = ROOT / ".gemini_quota.json"
MAX_RETRY_WAIT_SECONDS: int = 25


# ─── Model catalogue ──────────────────────────────────────────────────────────
@dataclass
class _ModelSpec:
    name: str          # API identifier
    rpm: int           # requests per minute (free tier)
    rpd: int           # requests per day (free tier)
    tier: int          # 1 = Flash, 2 = Flash-Lite, 3 = Gemma


# Gemini Flash — 20 RPD each, 5–6 RPM
_FLASH = [
    _ModelSpec("gemini-3.8-flash",   rpm=6,  rpd=20,    tier=1),
    _ModelSpec("gemini-3.7-flash",   rpm=6,  rpd=20,    tier=1),
    _ModelSpec("gemini-3.6-flash",   rpm=6,  rpd=20,    tier=1),
    _ModelSpec("gemini-3.5-flash",   rpm=6,  rpd=20,    tier=1),
    _ModelSpec("gemini-3-flash",     rpm=5,  rpd=20,    tier=1),
    _ModelSpec("gemini-2.5-flash",   rpm=5,  rpd=20,    tier=1),
]

# Gemini Flash Lite — 500 RPD each, 8–15 RPM
_FLASH_LITE = [
    _ModelSpec("gemini-3.5-flash-lite", rpm=15, rpd=500, tier=2),
    _ModelSpec("gemini-3.1-flash-lite", rpm=15, rpd=500, tier=2),
]

# Gemma 4 — 14,400 RPD each, 30 RPM
_GEMMA = [
    _ModelSpec("gemma-4-26b", rpm=30, rpd=14_400, tier=3),
    _ModelSpec("gemma-4-31b", rpm=30, rpd=14_400, tier=3),
]

_ALL_MODELS: dict[str, _ModelSpec] = {
    m.name: m for m in (_FLASH + _FLASH_LITE + _GEMMA)
}


# ─── Call types and their preferred model ordering ────────────────────────────
class CallType(str, Enum):
    SCRIPT_GEN  = "script_gen"   # Main video script — want highest quality
    FACT_CHECK  = "fact_check"   # Fact-verification pass — Gemma is great here
    SEO         = "seo"          # Title/description/tags — mid-quality fine
    JSON_REPAIR = "json_repair"  # Fix malformed JSON — any model fine


# Ordered list of model names per call type.
# Models exhausted or blacklisted are skipped at runtime.
_CALL_ORDER: dict[CallType, list[str]] = {
    CallType.SCRIPT_GEN: [
        # Tier 1 first — best quality for the viewer-facing script
        "gemini-3.8-flash",
        "gemini-3.7-flash",
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-3-flash",
        "gemini-2.5-flash",
        # Tier 2 fallback
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
        # Tier 3 last resort — Gemma can handle script gen in a pinch
        "gemma-4-26b",
        "gemma-4-31b",
    ],
    CallType.FACT_CHECK: [
        # Tier 3 first — Gemma has massive daily budget, perfect for fact checks
        "gemma-4-26b",
        "gemma-4-31b",
        # Tier 2 backup
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
        # Tier 1 last resort (preserve for script gen)
        "gemini-3.8-flash",
        "gemini-3.5-flash",
    ],
    CallType.SEO: [
        # Tier 2 first — saves Tier 1 RPD for script generation
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
        # Tier 1 fallback
        "gemini-3.8-flash",
        "gemini-3.7-flash",
        "gemini-3.5-flash",
        # Tier 3 last resort
        "gemma-4-26b",
        "gemma-4-31b",
    ],
    CallType.JSON_REPAIR: [
        # Tier 2 — low quality bar, just need valid JSON
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
        # Tier 1 fallback
        "gemini-3.8-flash",
        "gemini-3.5-flash",
        # Tier 3 last resort
        "gemma-4-26b",
        "gemma-4-31b",
    ],
}


# ─── Persisted quota state ─────────────────────────────────────────────────────
@dataclass
class _QuotaState:
    day: str                          # ISO date string (UTC)
    used: dict[str, int] = field(default_factory=dict)  # model → calls today

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


# ─── Helpers ──────────────────────────────────────────────────────────────────
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
    """Return True only for per-day exhaustion, never for short-window RPM spikes.

    Key distinction:
    - Daily exhaustion → GenerateRequestsPerDayPerProjectPerModel in the message,
      OR quota + day language, BUT only when there is no retry_delay hint.
    - RPM spike        → 429 with retry_delay { seconds: N } — these are short
      windows (usually 10-60 s) and the model should be retried, not blacklisted.

    A retry_delay in the message always signals a recoverable RPM limit, so we
    check for its absence before declaring daily exhaustion, regardless of what
    other keywords are present.
    """
    msg = str(exc)
    # If the API provided a retry_delay hint, this is an RPM spike, not a daily limit.
    if "retry_delay" in msg or re.search(r"retry in\s+[\d.]+s", msg, re.I):
        return False
    return (
        "GenerateRequestsPerDayPerProjectPerModel" in msg
        or ("quota" in msg.lower() and "day" in msg.lower())
    )


# ─── Router ───────────────────────────────────────────────────────────────────
class GeminiRouter:
    """Quota-aware Gemini router.  One instance per pipeline run is fine —
    it shares the persisted state file between runs on the same calendar day."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._state = _load_state()
        self._session_blacklist: set[str] = set()  # non-retriable failures
        genai.configure(api_key=api_key)

    # ── Public API ────────────────────────────────────────────────────────────
    def generate(self, prompt: str, call_type: CallType = CallType.SCRIPT_GEN) -> str:
        """Generate text, routing through models by call type and quota."""
        order = _CALL_ORDER[call_type]
        last_exc: Exception | None = None

        for model_name in order:
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
                    text = self._call(model_name, prompt)
                    self._state.record(model_name)
                    _save_state(self._state)
                    spec = _ALL_MODELS[model_name]
                    remaining = spec.rpd - self._state.calls_today(model_name)
                    print(f"[router] {model_name} OK ({call_type.value}) — {remaining} RPD left today")
                    return text

                except Exception as exc:
                    is_429 = "429" in str(exc) or "quota" in str(exc).lower()

                    if is_429 and _is_daily_quota_error(exc):
                        # Mark as exhausted in the persisted state so future
                        # runs on the same day also skip this model.
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

                    # Non-quota error or already retried → blacklist for this session
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

    # ── Private ───────────────────────────────────────────────────────────────
    def _call(self, model_name: str, prompt: str) -> str:
        model = genai.GenerativeModel(
            model_name,
            generation_config={
                "temperature": 0.75,
                "response_mime_type": "application/json",
            },
        )
        resp = model.generate_content(prompt)
        text = getattr(resp, "text", None)
        if not text:
            raise RuntimeError(f"Gemini ({model_name}) returned an empty response")
        return text
