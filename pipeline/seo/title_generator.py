"""SEO V3 — Title Generator with 3 strategic modes."""
from __future__ import annotations

import re
from enum import Enum
from .keyword_clusters import KeywordCluster

class TitleMode(Enum):
    SEARCH_FIRST = "search_first"   # concept | EXAM
    EXAM_FIRST = "exam_first"       # EXAM: concept
    PROBLEM_FIRST = "problem_first" # concept: curiosity hook

TITLE_MAX_CHARS = 90

def _truncate(title: str, max_chars: int = TITLE_MAX_CHARS) -> str:
    if len(title) <= max_chars:
        return title
    cut = title[:max_chars].rsplit(" ", 1)[0]
    return cut.rstrip(" :-,|–—")

def generate_seo_title(
    cluster: KeywordCluster,
    mode: TitleMode = TitleMode.SEARCH_FIRST,
    problem_hook: str = "",
) -> str:
    primary = cluster.primary_query
    exam = cluster.exams[0] if cluster.exams else ""

    if mode == TitleMode.SEARCH_FIRST:
        domain_label = cluster.domain[0] if cluster.domain else ""
        concept_part = f"{primary} in {domain_label}" if domain_label else primary
        title = f"{concept_part} | {exam}" if exam else concept_part
    elif mode == TitleMode.EXAM_FIRST:
        title = f"{exam}: {primary}" if exam else primary
    else:  # PROBLEM_FIRST
        if not problem_hook:
            return generate_seo_title(cluster, TitleMode.SEARCH_FIRST)
        title = f"{primary}: {problem_hook}"

    return _truncate(title)

def pick_title_mode(topic: str, cluster: KeywordCluster) -> TitleMode:
    topic_lower = topic.lower()
    curiosity_signals = ["trap", "trick", "mistake", "wrong", "confusion", "why", "secret", "pitfall"]
    if any(sig in topic_lower for sig in curiosity_signals):
        return TitleMode.PROBLEM_FIRST

    exam_patterns = [r"\bibps\b", r"\bsbi\b", r"\brbi\b", r"\bnabard\b", r"\bsebi\b"]
    for pat in exam_patterns:
        m = re.search(pat, topic_lower)
        if m and m.start() < 10:
            return TitleMode.EXAM_FIRST

    return TitleMode.SEARCH_FIRST

def extract_problem_hook(topic: str) -> str:
    """Return a viewer-facing curiosity phrase, not an explanatory label."""
    topic_lower = topic.lower()
    for pattern, template in [
        (r"\btrap\b|\bwrong\b|\bmistake\b|\bpitfall\b", "Can You Spot the Trap?"),
        (r"\btrick\b|\bshortcut\b|\bfastest\b", "Can You Solve It in 5 Seconds?"),
        (r"\bvs\.?\b|\bversus\b|\bdifference\b", "Which One Is Correct?"),
        (r"\bwhy\b|\bhow\b", "Do You Know Why?"),
        (r"\brule\b|\btest\b", "Do You Know the Rule?"),
        (r"\bsecret\b", "Would You Notice This?"),
    ]:
        if re.search(pattern, topic_lower):
            return template
    return "Can You Get This Right?"
