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

import random

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
    """Return a trending query string for the niche, or the fallback if unavailable."""
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
