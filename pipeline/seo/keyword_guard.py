"""SEO V3 — Keyword Density Guard."""
from __future__ import annotations
import re
from dataclasses import dataclass

@dataclass
class KeywordDensityResult:
    ok: bool
    missing_surfaces: list[str]
    suggestions: list[str]

def _contains_query(text: str, query: str, min_overlap: float = 0.6) -> bool:
    if not text or not query:
        return False
    text_lower = text.lower()
    if query.lower() in text_lower:
        return True
    query_tokens = [t for t in re.findall(r"[a-z0-9]+", query.lower()) if len(t) > 1]
    if not query_tokens:
        return True
    text_tokens = set(re.findall(r"[a-z0-9]+", text_lower))
    hits = sum(1 for t in query_tokens if t in text_tokens or any(
        tt.startswith(t[:4]) for tt in text_tokens if len(t) >= 4
    ))
    return (hits / len(query_tokens)) >= min_overlap

def validate_keyword_density(
    primary_query: str,
    title: str,
    description: str,
    narration_all: str,
    screen_texts: list[str],
) -> KeywordDensityResult:
    missing: list[str] = []
    suggestions: list[str] = []

    if not _contains_query(title, primary_query):
        missing.append("title")
        suggestions.append(f'Add "{primary_query}" to title.')

    desc_first = description[:200] if description else ""
    if not _contains_query(desc_first, primary_query):
        missing.append("description")
        suggestions.append(f'Start description with "{primary_query} explained".')

    if not _contains_query(narration_all, primary_query, min_overlap=0.5):
        missing.append("narration")
        suggestions.append(f'Say "{primary_query}" explicitly in narration.')

    screen_combined = " ".join(screen_texts)
    if not _contains_query(screen_combined, primary_query, min_overlap=0.4):
        missing.append("on_screen_text")
        suggestions.append(f'Display "{primary_query}" on screen.')

    return KeywordDensityResult(
        ok=len(missing) == 0,
        missing_surfaces=missing,
        suggestions=suggestions,
    )

def auto_repair_narration(narration: str, primary_query: str) -> str:
    if _contains_query(narration, primary_query, min_overlap=0.5):
        return narration
    return f"Let's understand {primary_query}. " + narration

def auto_repair_screen_text(screen_texts: list[str], primary_query: str) -> list[str]:
    combined = " ".join(screen_texts)
    if _contains_query(combined, primary_query, min_overlap=0.4):
        return screen_texts
    if len(screen_texts) > 1:
        words = primary_query.split()
        label = " ".join(words[:4]).upper()
        screen_texts[1] = label
    return screen_texts
