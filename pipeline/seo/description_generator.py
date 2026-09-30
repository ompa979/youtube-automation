"""SEO V3 — Description and Tag Generator."""
from __future__ import annotations
from .keyword_clusters import KeywordCluster

def generate_v3_description(
    cluster: KeywordCluster,
    topic_context: str = "",
    engagement_question: str = "",
) -> str:
    primary = cluster.primary_query
    exam = cluster.exams[0] if cluster.exams else ""
    domain = cluster.domain[0] if cluster.domain else "the concept"
    line1 = f"Learn {primary} in simple terms" + (f" for {exam}" if exam else "") + "."
    context = topic_context.strip().replace("\n", " ")[:180]
    line2 = context.rstrip(".") + "." if context else f"This Short breaks down the key {domain} idea and shows one practical example."
    line3 = engagement_question.strip() if engagement_question.strip() else "Save this Short as a quick revision note before your next mock."
    return "\n\n".join([line1, line2, line3])

def generate_v3_tags(cluster: KeywordCluster) -> list[str]:
    candidates = [cluster.primary_query.lower()]
    candidates.extend(e.lower() for e in cluster.exams[:2])
    candidates.extend(d.lower() for d in cluster.domain[:1])
    candidates.extend(x.lower() for x in cluster.long_tail[:3])
    candidates.append(cluster.short_query.lower())
    seen: set[str] = set()
    result: list[str] = []
    for tag in candidates:
        clean = " ".join(tag.split())
        if clean and clean not in seen:
            seen.add(clean); result.append(clean)
    return result[:10]
