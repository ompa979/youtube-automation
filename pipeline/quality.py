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

MIN_SCENES = 6
MAX_SCENES = 6

# V2 is intentionally compact. The challenge architecture targets roughly
# 18-28 seconds of spoken content, so the hard word ceiling is 65.
WORDS_PER_SECOND = 2.35
MIN_WORDS = 45
MAX_WORDS = 65


@dataclass
class QAResult:
    ok: bool
    issues: list[str]


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text.lower()))


def validate_script(script: Any, language: str) -> QAResult:
    issues: list[str] = []
    all_text = " ".join([script.title, script.hook] + [s.narration for s in script.scenes]).strip()
    spoken_text = " ".join(s.narration for s in script.scenes).strip()
    words = _word_count(spoken_text)

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

    expected_actions = ["pattern_interrupt", "challenge", "countdown", "reveal", "mechanism", "trap_loop"]
    actual_actions = [getattr(scene, "action_type", "") for scene in script.scenes]
    if actual_actions != expected_actions:
        issues.append(
            f"invalid V2 scene contract: expected {expected_actions}, got {actual_actions}"
        )

    if words < MIN_WORDS:
        issues.append(f"spoken narration only {words} words — needs at least {MIN_WORDS} words for the V2 challenge arc")
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
