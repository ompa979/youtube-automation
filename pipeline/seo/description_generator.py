"""SEO V3 — Description and Tag Generator."""
from __future__ import annotations
from .keyword_clusters import KeywordCluster

def generate_v3_description(
    cluster: KeywordCluster,
    topic_context: str = "",
    engagement_question: str = "",
) -> str:
    primary = cluster.primary_query
    concept = cluster.concept_query
    exam = cluster.exams[0] if cluster.exams else "bank exams"
    domain = cluster.domain[0] if cluster.domain else ""

    if domain:
        line1 = f"{concept} explained for {exam}."
    else:
        line1 = f"{primary} explained for {exam}."

    if topic_context:
        line2 = topic_context.rstrip(".") + "."
    else:
        line2 = f"This is a commonly tested concept in {exam} and similar banking examinations."

    if engagement_question:
        line3 = engagement_question.rstrip("?") + "?"
    else:
        line3 = f"Can you answer a {primary} question in under 10 seconds? Comment below!"

    line4 = "Subscribe to ExamCrackerAI for daily exam concepts, shortcuts and MCQs."
    return "\n\n".join([line1, line2, line3, line4])

def generate_v3_tags(cluster: KeywordCluster) -> list[str]:
    tags = []
    tags.append(cluster.primary_query.lower())
    for exam in cluster.exams[:2]:
        tags.append(exam.lower())
    if cluster.domain:
        tags.append(cluster.domain[0].lower())

    seen: set[str] = set()
    unique_tags: list[str] = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            unique_tags.append(t)
    return unique_tags[:5]
