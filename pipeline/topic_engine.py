"""Evidence-oriented topic selection for ExamCracker.

The selector treats topic choice as a product decision, not random rotation:
search intent + exam fit + teachability + visual potential + freshness + trend signal
- sensational/factually risky wording.

Network enrichment is optional and cached. If Google Trends / YouTube suggestions
are unavailable, deterministic scoring still works.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import requests

from .seo.keyword_clusters import get_cluster_for_topic

CACHE_PATH = Path(os.getenv("TOPIC_INTELLIGENCE_CACHE", ".topic_intelligence.json"))
CACHE_TTL_SECONDS = int(os.getenv("TOPIC_INTELLIGENCE_TTL", str(6 * 60 * 60)))

RISK_TERMS = (
    "90%", "99%", "every year", "always asks", "always asked", "illegal",
    "guaranteed", "secret", "hack any", "clone", "crack every", "never",
    "shocking", "you won't believe", "must watch",
)

SEARCH_INTENT_TERMS = (
    "vs", "difference", "what is", "how does", "why", "rule", "formula",
    "classification", "shortcut", "example", "steps", "layers", "trick",
)

VISUAL_TERMS = (
    "flow", "layer", "layers", "handshake", "packet", "table", "query", "key",
    "formula", "diagram", "process", "timeline", "money", "bank", "rbi",
    "code", "binary", "tree", "graph", "deposit", "ratio", "reserve", "npa",
    "example", "transaction", "node", "route", "table", "row", "root", "chart",
)

MECHANISM_TERMS = (
    "how", "why", "difference", "vs", "rule", "formula", "example", "steps",
    "process", "classification", "shortcut", "works", "condition", "flow", "method",
)
VALUE_TERMS = (
    "example", "difference", "vs", "rule", "formula", "shortcut", "steps", "process",
    "classification", "output", "digits", "query", "handshake", "layer", "purpose", "method",
)

EXAM_TERMS = (
    "ibps", "sbi", "rbi", "nabard", "sebi", "rrb", "ssc", "gate", "upsc",
)



EXAM_ONLY = os.getenv("EXAM_ONLY", "true").strip().lower() in {"1", "true", "yes", "on"}
ALLOWED_EXAM_NICHES = {
    "bank_it_officer", "bank_reasoning_quant", "banking_awareness",
    "rbi_economy", "bank_english", "ssc_general",
}
NON_EXAM_TOPIC_TERMS = (
    "sleep", "doorway effect", "feynman technique", "motivation", "fitness",
    "relationship", "pet", "travel", "beauty", "recipe", "cooking", "life hack",
    "psychology", "productivity hack", "morning routine", "brain hack",
)

NICHE_EXAM_FIT = {
    "bank_it_officer": 20.0,
    "bank_reasoning_quant": 20.0,
    "banking_awareness": 21.0,
    "rbi_economy": 21.0,
    "bank_english": 17.0,
    "ssc_general": 17.0,
}

@dataclass
class TopicScore:
    topic: str
    niche: str
    trend_score: float
    seo_score: float
    search_intent: float
    exam_fit: float
    specificity: float
    teachability: float
    visual: float
    value_density: float
    seo_fit: float
    freshness: float
    trend: float
    risk_penalty: float
    duplicate_penalty: float
    total: float
    reasons: list[str]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]{2,}", _norm(text))


def _load_cache() -> dict[str, Any]:
    try:
        if CACHE_PATH.exists():
            payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
    except Exception:
        pass
    return {}


def _save_cache(cache: dict[str, Any]) -> None:
    try:
        CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _cache_key(prefix: str, text: str) -> str:
    return prefix + ":" + hashlib.sha1(_norm(text).encode("utf-8")).hexdigest()[:20]


def youtube_suggestions(query: str) -> list[str]:
    """Best-effort YouTube autocomplete; no API key required. Cached aggressively."""
    cache = _load_cache()
    key = _cache_key("yt", query)
    entry = cache.get(key)
    now = time.time()
    if isinstance(entry, dict) and now - float(entry.get("ts", 0)) < CACHE_TTL_SECONDS:
        return [str(x) for x in entry.get("items", [])]

    try:
        r = requests.get(
            "https://suggestqueries.google.com/complete/search",
            params={"client": "firefox", "ds": "yt", "q": query},
            timeout=8,
            headers={"User-Agent": "ExamCrackerTopicEngine/1.0"},
        )
        r.raise_for_status()
        data = r.json()
        raw = data[1] if isinstance(data, list) and len(data) > 1 else []
        items = [str(x[0] if isinstance(x, list) else x) for x in raw if x]
    except Exception as exc:
        print(f"[topic] YouTube autocomplete unavailable for {query!r}: {exc}")
        items = []

    cache[key] = {"ts": now, "items": items[:12]}
    _save_cache(cache)
    return items[:12]


def _trend_scores(topics: list[str]) -> dict[str, float]:
    """Best-effort Google Trends relative score for up to five topics at a time."""
    if os.getenv("TOPIC_USE_TRENDS", "true").strip().lower() not in {"1", "true", "yes", "on"}:
        return {t: 0.0 for t in topics}
    if not topics:
        return {}
    try:
        from pytrends.request import TrendReq  # type: ignore
        pt = TrendReq(hl="en-IN", tz=330, timeout=(8, 15), retries=1, backoff_factor=0.4)
        result: dict[str, float] = {t: 0.0 for t in topics}
        for start in range(0, len(topics), 5):
            chunk = topics[start:start + 5]
            pt.build_payload(chunk, geo="IN", timeframe="today 3-m")
            df = pt.interest_over_time()
            if df is None or df.empty:
                continue
            for topic in chunk:
                if topic in df.columns:
                    series = df[topic].astype(float)
                    # Trend is momentum, not just historical volume: weight the most
                    # recent 21 days and compare it with the preceding 21-day window.
                    values = series.tolist()
                    if not values:
                        continue
                    recent = values[-21:]
                    previous = values[-42:-21] if len(values) >= 42 else values[:-21]
                    recent_mean = sum(recent) / max(1, len(recent))
                    previous_mean = sum(previous) / max(1, len(previous)) if previous else recent_mean
                    momentum = 0.0 if previous_mean <= 0 else max(-1.0, min(1.0, (recent_mean - previous_mean) / previous_mean))
                    # 70% current interest + 30% momentum. Still a relative signal
                    # because Google Trends itself is normalized within a comparison set.
                    result[topic] = max(0.0, min(100.0, recent_mean * 0.70 + (50.0 + 50.0 * momentum) * 0.30))
        return result
    except Exception as exc:
        print(f"[topic] Google Trends unavailable: {exc}")
        return {t: 0.0 for t in topics}


def _candidate_query_signal(topic: str) -> float:
    if os.getenv("TOPIC_USE_AUTOCOMPLETE", "true").strip().lower() not in {"1", "true", "yes", "on"}:
        return 0.0
    suggestions = youtube_suggestions(topic)
    if not suggestions:
        return 0.0
    topic_tokens = set(_tokens(topic))
    hits = 0
    for suggestion in suggestions:
        st = set(_tokens(suggestion))
        overlap = len(topic_tokens & st) / max(1, len(topic_tokens))
        if overlap >= 0.5:
            hits += 1
    return min(10.0, hits * 2.0)


def score_topic(
    topic: str,
    niche: str,
    completed_topics: set[str] | None = None,
    recent_topics: list[str] | None = None,
    trend: float = 0.0,
    query_signal: float | None = None,
) -> TopicScore:
    text = _norm(topic)
    tokens = _tokens(topic)
    completed_topics = {x.lower() for x in (completed_topics or set())}
    recent_topics = [x.lower() for x in (recent_topics or [])]
    reasons: list[str] = []

    # Search intent: explicit question/difference/rule language + YouTube autocomplete evidence.
    intent_hits = sum(term in text for term in SEARCH_INTENT_TERMS)
    query_signal = _candidate_query_signal(topic) if query_signal is None else query_signal
    search = min(20.0, 7.0 + intent_hits * 2.1 + query_signal * 0.9)
    if intent_hits:
        reasons.append(f"search intent={intent_hits}")
    if query_signal > 0:
        reasons.append(f"YouTube autocomplete signal={query_signal:.1f}")

    # Exam fit: enabled exam lanes get a baseline; explicit exam terms add evidence.
    exam_fit = NICHE_EXAM_FIT.get(niche, 12.0)
    exam_hits = sum(term in text for term in EXAM_TERMS)
    if exam_hits:
        exam_fit = min(20.0, exam_fit + min(6.0, exam_hits * 3.0))
        reasons.append(f"exam fit evidence={exam_hits}")
    else:
        exam_fit = min(17.0, exam_fit)

    # Specificity: short enough for a query, specific enough to make a complete Short.
    specificity = 6.0 + min(10.0, max(0, len(tokens) - 3) * 1.3)
    if 5 <= len(tokens) <= 15:
        specificity += 2.0
        reasons.append("query-sized specificity")
    elif len(tokens) > 18:
        specificity -= 4.0
        reasons.append("topic is too broad/long")

    # Teachability/value density: one mechanism + one example should be possible.
    teach_hits = sum(term in text for term in MECHANISM_TERMS)
    teachability = 5.0 + min(10.0, teach_hits * 2.0)
    if teach_hits:
        reasons.append("clear teachable mechanism")
    else:
        reasons.append("weak teaching mechanism")

    value_density = 5.0
    value_hits = sum(term in text for term in VALUE_TERMS)
    if value_hits:
        value_density += min(7.0, value_hits * 2.0)
        reasons.append(f"utility terms={value_hits}")
    if len(tokens) <= 15:
        value_density += 2.5
    if any(x in text for x in ("definition", "meaning", "what is")):
        value_density += 1.0

    # Visual potential: concepts that can literally move/transform score higher.
    visual_hits = sum(term in text for term in VISUAL_TERMS)
    visual = 5.0 + min(12.0, visual_hits * 1.6)
    if visual_hits:
        reasons.append(f"visual mechanism terms={visual_hits}")

    # SEO fit: curated cluster / coherent primary query + domain/exam aliases.
    cluster = get_cluster_for_topic(topic)
    seo_fit = 4.0
    if cluster:
        primary_tokens = set(_tokens(cluster.primary_query))
        overlap = len(primary_tokens & set(tokens)) / max(1, len(primary_tokens))
        seo_fit += min(6.0, overlap * 6.0)
        # Query-specific evidence: exact primary query and long-tail suggestions are stronger than generic trend volume.
        suggestion_text = youtube_suggestions(cluster.primary_query) if os.getenv("TOPIC_USE_AUTOCOMPLETE", "true").strip().lower() in {"1", "true", "yes", "on"} else []
        if suggestion_text:
            exactish = sum(1 for item in suggestion_text if cluster.primary_query.lower() in item.lower())
            seo_fit += min(3.0, exactish * 1.5)
            if exactish:
                reasons.append(f"SEO autocomplete exact={exactish}")
        reasons.append(f"SEO primary={cluster.primary_query}")

    # Freshness and duplicate protection.
    low = text
    freshness = 10.0
    if low in completed_topics:
        freshness = 0.0
        reasons.append("already published")
    elif any(low == r or low in r or r in low for r in recent_topics):
        freshness = 2.0
        reasons.append("recently used")
    else:
        freshness += 1.0

    trend_score = min(100.0, max(0.0, float(trend)))
    seo_score = min(100.0, max(0.0, seo_fit * 8.0 + search * 2.2 + query_signal * 1.5))
    if trend_score > 0:
        reasons.append(f"trend momentum signal={trend_score:.1f}")
    else:
        reasons.append("trend signal unavailable/flat")
    reasons.append(f"SEO evidence score={seo_score:.1f}")

    risk_terms = [term for term in RISK_TERMS if term in text]
    risk_penalty = min(18.0, len(risk_terms) * 5.0) if risk_terms else 0.0
    if risk_terms:
        reasons.append("sensational/unsupported wording")
    duplicate_penalty = 10.0 if any(low == r for r in recent_topics[:5]) else 0.0

    # Discovery-first weighting: Trend is the first gate, SEO the second gate.
    # Remaining scores are normalized to the same 0-100 scale for an interpretable total.
    exam_norm = (exam_fit / 20.0) * 100.0
    value_norm = (value_density / 20.0) * 100.0
    visual_norm = (visual / 20.0) * 100.0
    specificity_norm = (specificity / 20.0) * 100.0
    teach_norm = (teachability / 15.0) * 100.0
    freshness_norm = (freshness / 11.0) * 100.0
    total = (
        trend_score * 0.30 +
        seo_score * 0.25 +
        exam_norm * 0.17 +
        value_norm * 0.11 +
        visual_norm * 0.07 +
        specificity_norm * 0.04 +
        teach_norm * 0.03 +
        freshness_norm * 0.03
        - risk_penalty - duplicate_penalty
    )
    total = round(max(0.0, min(100.0, total)), 2)

    return TopicScore(
        topic=topic, niche=niche, trend_score=round(trend_score, 2), seo_score=round(seo_score, 2),
        search_intent=round(search, 2), exam_fit=round(exam_fit, 2), specificity=round(specificity, 2),
        teachability=round(teachability, 2), visual=round(visual, 2), value_density=round(value_density, 2),
        seo_fit=round(seo_fit, 2), freshness=round(freshness, 2), trend=round(trend_score, 2),
        risk_penalty=round(risk_penalty, 2), duplicate_penalty=round(duplicate_penalty, 2), total=total, reasons=reasons,
    )


def choose_best_topic(plan: dict[str, Any], enabled_niches: list[str], state: dict[str, Any]) -> tuple[str, dict[str, Any], str, str, TopicScore, list[TopicScore]]:
    recent_topics = list(state.get("recent_topics") or [])
    completed = set(state.get("completed_topics") or [])
    candidates: list[tuple[str, dict[str, Any], str]] = []
    filtered_niches = [
        n for n in enabled_niches
        if (not EXAM_ONLY or n in ALLOWED_EXAM_NICHES)
    ]
    if EXAM_ONLY and not filtered_niches:
        # Hard safety rail: a misconfigured environment can never force a
        # lifestyle/non-exam topic into an exam-prep run. Fall back to all
        # available exam lanes in the content plan.
        filtered_niches = [
            n for n in sorted(ALLOWED_EXAM_NICHES)
            if n in plan and plan.get(n, {}).get("topics") and plan.get(n, {}).get("voice")
        ]
    for niche in filtered_niches:
        cfg = plan.get(niche, {})
        voice = cfg.get("voice", {})
        if not cfg.get("topics") or not voice:
            continue
        # Sample more candidates from higher-priority niches, but never exhaust the full pool.
        # This preserves diversity while giving IT/banking topics more chances to win on evidence.
        cursor = int(state.get("topic_cursors", {}).get(niche, 0))
        topics = cfg["topics"]
        weight = max(1, int(cfg.get("weight", 1)))
        sample_count = min(6, max(3, weight + 2))
        for offset in range(min(sample_count, len(topics))):
            candidate_topic = topics[(cursor + offset) % len(topics)]
            if EXAM_ONLY and any(term in _norm(candidate_topic) for term in NON_EXAM_TOPIC_TERMS):
                continue
            candidates.append((niche, cfg, candidate_topic))

    if not candidates:
        raise RuntimeError("Topic engine found no viable candidates")

    # First pass is deterministic and cheap. Only the strongest candidates are sent to
    # autocomplete/trends because network enrichment is the expensive part of selection.
    rough: list[TopicScore] = []
    meta: dict[str, tuple[str, dict[str, Any], str]] = {}
    for niche, cfg, topic in candidates:
        score = score_topic(topic, niche, completed, recent_topics, trend=0.0, query_signal=0.0)
        rough.append(score)
        meta[topic] = (niche, cfg, topic)
    rough.sort(key=lambda x: x.total, reverse=True)
    top_topics = [x.topic for x in rough[:12]]
    trend_values = _trend_scores(top_topics)
    # If the provider returns no usable values, use a clearly conservative neutral
    # signal rather than pretending "0" means "not trending". This prevents an
    # outage from silently dominating topic selection.
    usable = [float(v) for v in trend_values.values() if float(v) > 0]
    if not usable:
        trend_values = {topic: 35.0 for topic in top_topics}
    elif len(usable) > 1:
        # Make the score comparable inside this candidate board while preserving
        # the provider's absolute signal. This is why the dashboard can put Trend
        # first without allowing tiny raw 0/1 values to masquerade as absolute scores.
        lo, hi = min(usable), max(usable)
        if hi > lo:
            for topic in list(trend_values):
                raw = float(trend_values.get(topic, 0.0))
                trend_values[topic] = 20.0 + 80.0 * ((raw - lo) / (hi - lo)) if raw > 0 else 15.0

    scored: list[TopicScore] = []
    for item in rough:
        if item.topic not in top_topics:
            scored.append(item)
            continue
        qs = _candidate_query_signal(item.topic)
        scored.append(score_topic(item.topic, item.niche, completed, recent_topics, trend_values.get(item.topic, 35.0), query_signal=qs))

    # Discovery order is literal: Trend first, then SEO, then exam fit/value/visual.
    # Total remains an audit metric, never the primary selector.
    scored.sort(key=lambda x: (x.trend_score, x.seo_score, x.exam_fit, x.value_density, x.visual, x.total), reverse=True)

    # Hard quality gates: a topic must be useful even if it is temporarily popular.
    viable = [x for x in scored if x.exam_fit >= 12.0 and x.value_density >= 9.0 and x.teachability >= 7.0 and x.seo_fit >= 4.0]
    if viable:
        scored = viable + [x for x in scored if x not in viable]

    # Avoid the same niche on consecutive videos unless its score is materially higher.
    last_niche = state.get("last_niche")
    top = scored[0]
    for candidate in scored[1:4]:
        if last_niche and candidate.niche != last_niche and candidate.total >= top.total - 6:
            top = candidate
            break

    niche, cfg, topic = meta[top.topic]
    language = next(iter(cfg.get("voice", {"en": "en-IN"})))
    # Persist a compact intelligence board so the pipeline can audit why a topic won.
    cache = _load_cache()
    cache["latest_selection"] = {
        "ts": time.time(),
        "selected": top.as_dict(),
        "board": [x.as_dict() for x in scored[:10]],
        "exam_only": EXAM_ONLY,
        "allowed_niches": sorted(ALLOWED_EXAM_NICHES),
    }
    _save_cache(cache)
    return niche, cfg, language, topic, top, scored[:10]
