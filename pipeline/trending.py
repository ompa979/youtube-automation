"""Trending topic discovery via Google Trends (Pytrends — free, no API key).

Used as an optional enrichment layer: if pytrends is available and returns
results, the pipeline picks a trending query related to the niche instead
of the next static topic from content_plan.json.

Falls back gracefully to the static topic list if:
  - pytrends is not installed
  - Google Trends is rate-limited or unavailable
  - No relevant trending queries are found
"""
from __future__ import annotations

import os
import random

_URLLIB3_SHIMMED = False


def _patch_urllib3_method_whitelist() -> None:
    """pytrends (as of 4.9.2) still constructs urllib3's `Retry(...)` with the
    legacy `method_whitelist=` kwarg. urllib3>=2.0 renamed that to
    `allowed_methods=` and dropped the old name entirely, so on any
    environment that resolves a modern urllib3 (neither requirements.txt
    pins it) this raises:
        Retry.__init__() got an unexpected keyword argument 'method_whitelist'
    which is swallowed by our broad `except Exception` below, so trending
    topics silently never work — every run falls back to the static list.

    Rather than pin urllib3 to an old major version (which risks fighting
    other pinned deps), shim Retry.__init__ once per process to accept the
    old kwarg name, mapping it to the new one.
    """
    global _URLLIB3_SHIMMED
    if _URLLIB3_SHIMMED:
        return
    _URLLIB3_SHIMMED = True
    try:
        from urllib3.util.retry import Retry
    except ImportError:
        return
    if "method_whitelist" in Retry.__init__.__code__.co_varnames:
        return  # already supported natively (urllib3 < 2) — nothing to shim

    _orig_init = Retry.__init__

    def _patched_init(self, *args, method_whitelist=None, **kwargs):
        if method_whitelist is not None and "allowed_methods" not in kwargs:
            kwargs["allowed_methods"] = method_whitelist
        _orig_init(self, *args, **kwargs)

    Retry.__init__ = _patched_init


_NICHE_SEED_KEYWORDS: dict[str, list[str]] = {
    "exam_concepts": ["UPSC", "NEET", "JEE", "SSC", "India GK"],
    "science_explainers": ["science facts", "physics", "chemistry", "biology India"],
    "facts": ["amazing facts", "did you know", "India facts"],
    "history": ["Indian history", "ancient India", "freedom fighters"],
    "geography": ["Indian geography", "world geography", "map"],
    "economics": ["Indian economy", "GDP", "inflation India"],
}

_DEFAULT_SEED = ["India education", "exam preparation"]


def get_trending_topic(niche: str, fallback_topic: str) -> str:
    """Return a trending query string for the niche, or the fallback if unavailable.

    Disabled by default (USE_TRENDS=true to enable). Google Trends "related queries"
    are news-style searches (results, admit cards, dates) that drift off the channel's
    exam lane and can't be taught accurately; a run that asked for "neet pg 2026"
    published an unrelated eye-condition video. The lane-locked topic list is used instead.
    """
    if os.getenv("USE_TRENDS", "false").strip().lower() != "true":
        return fallback_topic
    _patch_urllib3_method_whitelist()
    try:
        from pytrends.request import TrendReq  # type: ignore
    except ImportError:
        print("[trends] pytrends not installed — using static topic")
        return fallback_topic

    seeds = _NICHE_SEED_KEYWORDS.get(niche, _DEFAULT_SEED)
    try:
        pt = TrendReq(hl="en-IN", tz=330, timeout=(10, 25), retries=2, backoff_factor=0.5)
        pt.build_payload(seeds[:5], geo="IN", timeframe="now 7-d")
        related = pt.related_queries()

        candidates: list[str] = []
        for seed in seeds:
            block = related.get(seed, {})
            top = block.get("top")
            if top is not None and not top.empty:
                queries = top["query"].tolist()[:5]
                candidates.extend(queries)

        # Filter: keep only reasonably short, educational-looking queries
        candidates = [
            q for q in candidates
            if 5 < len(q) < 80 and not any(c.isdigit() for c in q[:3])
        ]

        if candidates:
            chosen = random.choice(candidates)
            print(f"[trends] trending topic for niche={niche!r}: {chosen!r}")
            return chosen

    except Exception as exc:
        print(f"[trends] Google Trends unavailable ({exc}) — using static topic")

    return fallback_topic
