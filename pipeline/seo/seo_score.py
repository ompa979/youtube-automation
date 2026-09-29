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
        title_score += 15
        breakdown.append("[+] title contains primary query (+15)")
    else:
        breakdown.append("[-] title missing primary query")

    if cluster.exams and any(e.lower() in title.lower() for e in cluster.exams):
        title_score += 8
        breakdown.append("[+] exam name in title (+8)")
    else:
        breakdown.append("[-] exam name missing from title")

    if 40 <= len(title) <= 90:
        title_score += 7
        breakdown.append(f"[+] title length {len(title)} chars (+7)")
    elif len(title) < 40:
        title_score += 3
        breakdown.append(f"[!] title short ({len(title)} chars) (+3)")
    else:
        breakdown.append(f"[-] title too long ({len(title)} chars)")

    desc_score = 0
    desc_first = description[:200]
    if _contains_query(desc_first, primary):
        desc_score += 10
        breakdown.append("[+] description opens with primary query (+10)")
    else:
        breakdown.append("[-] description missing primary query in first 200 chars")

    if cluster.exams and any(e.lower() in description.lower() for e in cluster.exams):
        desc_score += 8
        breakdown.append("[+] exam name in description (+8)")
    else:
        breakdown.append("[-] exam name missing from description")

    if "?" in description:
        desc_score += 4
        breakdown.append("[+] description has CTA question (+4)")
    else:
        breakdown.append("[-] description missing CTA question")

    if "subscribe" in description.lower() or "examcracker" in description.lower():
        desc_score += 3
        breakdown.append("[+] description has channel follow line (+3)")

    narration_score = 0
    if _contains_query(narration_all, primary, min_overlap=0.5):
        narration_score += 15
        breakdown.append("[+] primary query spoken in narration (+15)")
    else:
        breakdown.append("[-] narration missing primary query")

    domain_hits = sum(1 for d in cluster.domain if d.lower() in narration_all.lower())
    if domain_hits > 0:
        narration_score += 5
        breakdown.append(f"[+] {domain_hits} domain keyword(s) in narration (+5)")

    screen_combined = " ".join(screen_texts)
    screen_score = 0
    if _contains_query(screen_combined, primary, min_overlap=0.4):
        screen_score += 15
        breakdown.append("[+] primary query appears on screen (+15)")
    else:
        query_words = [w for w in primary.lower().split() if len(w) > 2]
        hits = sum(1 for w in query_words if w in screen_combined.lower())
        if hits > 0:
            screen_score += 7
            breakdown.append(f"[!] partial screen text match (+7)")
        else:
            breakdown.append("[-] primary query missing from screen text")

    tags_score = 0
    if 3 <= len(tags) <= 5:
        tags_score += 5
        breakdown.append(f"[+] ideal tag count ({len(tags)}) (+5)")
    elif 1 <= len(tags) < 3:
        tags_score += 2
        breakdown.append(f"[!] too few tags ({len(tags)}) (+2)")
    elif len(tags) > 10:
        breakdown.append(f"[-] too many tags ({len(tags)})")

    tags_text = " ".join(tags).lower()
    if _contains_query(tags_text, primary, min_overlap=0.5):
        tags_score += 5
        breakdown.append("[+] primary query covered in tags (+5)")
    else:
        breakdown.append("[-] primary query missing from tags")

    total = title_score + desc_score + narration_score + screen_score + tags_score
    return SEOScore(
        total=total,
        title_score=title_score,
        description_score=desc_score,
        narration_score=narration_score,
        screen_score=screen_score,
        tags_score=tags_score,
        breakdown=breakdown,
    )

def calculate_retention_score(scenes: list) -> RetentionScore:
    breakdown: list[str] = []
    total = 0
    if not scenes:
        return RetentionScore(total=0, breakdown=["[-] no scenes"])

    action_types = [getattr(s, "action_type", "") for s in scenes]

    if action_types and action_types[0] == "pattern_interrupt":
        total += 25
        breakdown.append("[+] scene 0 is pattern_interrupt (+25)")
    else:
        breakdown.append("[-] scene 0 should be pattern_interrupt")

    if "challenge" in action_types:
        total += 20
        breakdown.append("[+] challenge scene present (+20)")
    else:
        breakdown.append("[-] no challenge scene")

    if "reveal" in action_types:
        total += 20
        breakdown.append("[+] reveal scene present (+20)")
    else:
        breakdown.append("[-] no reveal scene")

    if "countdown" in action_types or "mechanism" in action_types:
        total += 15
        breakdown.append("[+] tension/mechanism scene present (+15)")
    else:
        breakdown.append("[-] no countdown/mechanism scene")

    if action_types and action_types[-1] in ("loop", "trap"):
        total += 20
        breakdown.append("[+] final scene is loop/CTA (+20)")
    elif action_types and "loop" in action_types:
        total += 10
        breakdown.append("[!] loop scene present but not last (+10)")
    else:
        breakdown.append("[-] final scene is not loop/CTA")

    return RetentionScore(total=total, breakdown=breakdown)

def calculate_final_publish_score(seo_score: int, retention_score: int) -> PublishScore:
    final = round(seo_score * 0.6 + retention_score * 0.4)
    return PublishScore(
        seo=seo_score,
        retention=retention_score,
        final=final,
        publish_ready=final >= 70,
    )
