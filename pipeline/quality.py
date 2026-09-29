"""Deterministic content QA for the natural ExamCracker Shorts pipeline."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .script_gen import Script

HINDI_MARKERS = {
    "hai", "hain", "kyun", "kyon", "kyunki", "ka", "ke", "ki", "ko", "se", "me", "mein",
    "aur", "lekin", "agar", "toh", "to", "ye", "yeh", "woh", "iska", "iske", "uska", "uske",
    "aap", "hum", "dekho", "samjho", "socho", "matlab", "sirf", "bhi", "jab", "jabki", "phir",
    "ek", "do", "kya", "kaise", "kyonki", "hota", "hote", "hoti", "karna", "karte", "liye",
    "yaad", "rakho", "exam", "question", "answer", "important", "reason", "wajah",
}
GENERIC_FILLERS = [
    "hello everyone", "welcome back", "guys aaj", "today we are going to",
    "in this video we will", "don't forget to subscribe",
    "let us understand", "as we know", "is defined as", "today we will learn",
]

MIN_SCENES = 3
MAX_SCENES = 6

# Rough spoken-word budget for a tight Short. At natural pace (~150 wpm /
# 2.5 words-per-second), this keeps total narration under ~65s.
# 65s is the practical ceiling: YouTube Shorts must be ≤60s of *video* but
# TTS renders slightly faster than the 2.5 wps estimate, so a 65s word-count
# target lands the rendered clip safely under 60s.  The previous 55s limit
# was triggering unnecessary repair loops on scripts that rendered fine.
# Calm educator pace (~130 wpm / 2.2 words-per-second).
# YouTube Shorts must be strictly under 60s total duration.
# 54s spoken audio gives a safe buffer for title and outro.
WORDS_PER_SECOND = 2.2
MAX_SPOKEN_SECONDS = 54
MAX_WORDS = int(MAX_SPOKEN_SECONDS * WORDS_PER_SECOND)  # ~118 words


@dataclass
class QAResult:
    ok: bool
    issues: list[str]


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text.lower()))


def validate_script(script: Any, language: str) -> QAResult:
    issues: list[str] = []
    all_text = " ".join([script.title, script.hook] + [s.narration for s in script.scenes]).strip()
    words = _word_count(all_text)

    if not script.title.strip():
        issues.append("missing title")
    if not script.hook.strip():
        issues.append("missing hook")

    # Hard scene count guardrail — enforced strictly for Shorts format
    scene_count = len(script.scenes)
    if scene_count < MIN_SCENES:
        issues.append(
            f"too few scenes ({scene_count}); minimum {MIN_SCENES} — "
            "add more scenes to cover the concept properly"
        )
    if scene_count > MAX_SCENES:
        issues.append(
            f"too many scenes ({scene_count}) for a Short; maximum {MAX_SCENES} — "
            "merge the least distinct scenes without losing the explanation"
        )

    if words < 25:
        issues.append("explanation is too thin to teach the concept; add the missing reasoning")
    if words > MAX_WORDS:
        est_seconds = round(words / WORDS_PER_SECOND)
        issues.append(
            f"script is ~{est_seconds}s of narration at natural educator pace — "
            f"YouTube Shorts hard limit is 60s; cut slightly to fit under {MAX_WORDS} words"
        )

    if any("\u0900" <= ch <= "\u097F" for ch in all_text):
        issues.append("English-only pipeline: Devanagari/Hindi text detected")

    for i, scene in enumerate(script.scenes, start=1):
        if not scene.narration.strip():
            issues.append(f"scene {i}: empty narration")
        if not scene.image_prompt.strip():
            issues.append(f"scene {i}: missing visual prompt")
        if len(scene.on_screen_text.split()) > 8:
            issues.append(f"scene {i}: too much on-screen text")
        if any(x in scene.narration.lower() for x in GENERIC_FILLERS):
            issues.append(f"scene {i}: generic AI filler/opening")

    if language != "en":
        issues.append(f"V5 requires language=en; received {language!r}")

    # Retention architecture check
    try:
        from .seo import calculate_retention_score
        action_types = [getattr(s, "action_type", "") for s in script.scenes]
        if any(action_types):
            ret = calculate_retention_score(script.scenes)
            if ret.total < 40:
                issues.append(
                    f"low retention score ({ret.total}/100) — "
                    "add a challenge or reveal scene to improve engagement"
                )
    except Exception:
        pass

    return QAResult(ok=not issues, issues=issues)
