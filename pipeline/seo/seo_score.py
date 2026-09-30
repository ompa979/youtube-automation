"""SEO V3 — Scoring engine."""
from __future__ import annotations
import re
from dataclasses import dataclass
from .keyword_clusters import KeywordCluster
from .keyword_guard import _contains_query

@dataclass
class SEOScore:
    total: int
    title_score: int
    description_score: int
    narration_score: int
    screen_score: int
    tags_score: int
    breakdown: list[str]

@dataclass
class RetentionScore:
    total: int
    breakdown: list[str]

@dataclass
class PublishScore:
    seo: int
    retention: int
    final: int
    publish_ready: bool

def calculate_seo_score(
    cluster: KeywordCluster,
    title: str,
    description: str,
    narration_all: str,
    screen_texts: list[str],
    tags: list[str],
) -> SEOScore:
    breakdown: list[str] = []
    primary = cluster.primary_query
    title_score = 0
    if _contains_query(title, primary):
        title_score += 25; breakdown.append("[+] title contains primary query (+25)")
    else: breakdown.append("[-] title missing primary query")
    if 45 <= len(title) <= 85:
        title_score += 10; breakdown.append("[+] title length is compact (+10)")
    if any(w in title.lower() for w in ("why", "how", "vs", "difference", "rule", "works")):
        title_score += 5; breakdown.append("[+] title has a natural curiosity/search qualifier (+5)")
    desc_score = 0
    if _contains_query(description[:220], primary):
        desc_score += 20; breakdown.append("[+] primary query in description opening (+20)")
    if any(k in description.lower() for k in ("learn", "understand", "example", "explains")):
        desc_score += 10; breakdown.append("[+] description communicates learning value (+10)")
    narration_score = 0
    if _contains_query(narration_all, primary, min_overlap=0.5):
        narration_score += 20; breakdown.append("[+] primary query appears naturally in narration (+20)")
    if cluster.domain and any(d.lower() in narration_all.lower() for d in cluster.domain):
        narration_score += 5; breakdown.append("[+] domain context is spoken (+5)")
    screen_combined = " ".join(screen_texts)
    screen_score = 0
    if _contains_query(screen_combined, primary, min_overlap=0.35):
        screen_score += 15; breakdown.append("[+] concept is visible on screen (+15)")
    tags_score = 0
    if 5 <= len(tags) <= 10:
        tags_score += 5; breakdown.append("[+] focused tag set (+5)")
    if _contains_query(" ".join(tags), primary, min_overlap=0.5):
        tags_score += 5; breakdown.append("[+] primary query represented in tags (+5)")
    total = min(100, title_score + desc_score + narration_score + screen_score + tags_score)
    return SEOScore(total=total, title_score=title_score, description_score=desc_score, narration_score=narration_score, screen_score=screen_score, tags_score=tags_score, breakdown=breakdown)

def calculate_retention_score(scenes: list) -> RetentionScore:
    breakdown: list[str] = []
    if not scenes:
        return RetentionScore(total=0, breakdown=["[-] no scenes"])
    roles = [getattr(s, "action_type", "") for s in scenes]
    total = 0
    expected = ["hook", "context", "mechanism", "example", "exam_takeaway", "memory_lock"]
    if roles == expected:
        total += 30; breakdown.append("[+] complete value-first scene arc (+30)")
    else:
        breakdown.append("[-] scene arc is not value-first")
    hook_words = len(getattr(scenes[0], "narration", "").split()) if scenes else 0
    if 7 <= hook_words <= 24:
        total += 15; breakdown.append("[+] concise specific hook (+15)")
    else:
        breakdown.append("[-] hook length needs improvement")
    if any(r == "mechanism" for r in roles):
        total += 20; breakdown.append("[+] mechanism explains the concept (+20)")
    if any(r == "example" for r in roles):
        total += 20; breakdown.append("[+] concrete example present (+20)")
    if any(r == "memory_lock" for r in roles):
        total += 15; breakdown.append("[+] final memory lock (+15)")
    return RetentionScore(total=min(100, total), breakdown=breakdown)

def calculate_final_publish_score(seo_score: int, retention_score: int) -> PublishScore:
    final = round(seo_score * 0.6 + retention_score * 0.4)
    return PublishScore(
        seo=seo_score,
        retention=retention_score,
        final=final,
        publish_ready=final >= 70,
    )
