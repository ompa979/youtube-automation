"""Deterministic quality gates for ExamCracker Creative V6."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

MIN_SCENES = 6
MAX_SCENES = 6
MIN_WORDS = 55
MAX_WORDS = 80
WORDS_PER_SECOND = 2.5

GENERIC_FILLERS = (
    "hello everyone", "welcome back", "guys aaj", "today we are going to",
    "in this video we will", "let us understand", "as we know", "subscribe for more",
    "don't forget to subscribe", "stop scrolling", "wait for it",
)
FORBIDDEN_GAME_LANGUAGE = re.compile(
    r"\b(a\s*(?:or|vs\.?|versus)\s*b|option\s*[a-d]|quick test|think fast|countdown|3\.\.\.\s*2|stop scrolling|stop|wait|reveal|the trick|did you get it)\b",
    re.I,
)
SENSATIONAL_UNVERIFIED = re.compile(
    r"(?<!\w)(?:90%|99%|every year|always asked|always asks|guaranteed|crack every|hack any|secret that|you will be shocked|most people do not know|most people don't know|shocking)(?!\w)",
    re.I,
)

@dataclass
class QAResult:
    ok: bool
    issues: list[str]


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text.lower()))


def validate_script(script: Any, language: str, content_mode: str = "exam") -> QAResult:
    issues: list[str] = []
    scenes = list(getattr(script, "scenes", []) or [])
    spoken = " ".join(s.narration for s in scenes).strip()
    all_text = " ".join([script.title, script.hook, script.description, script.pinned_comment] + [s.narration + " " + s.on_screen_text for s in scenes])
    words = _word_count(spoken)

    if not script.title.strip(): issues.append("missing title")
    if not script.hook.strip(): issues.append("missing hook")
    if len(scenes) != 6: issues.append(f"expected exactly 6 scenes, got {len(scenes)}")
    min_words = 60 if content_mode == "viral" else MIN_WORDS
    max_words = 100 if content_mode == "viral" else MAX_WORDS
    if words < min_words: issues.append(f"too short: {words} words; needs a complete idea")
    if words > max_words: issues.append(f"too long: {words} words; remove repetition")
    if language != "en": issues.append(f"V6 requires language=en, got {language!r}")
    if any("\u0900" <= ch <= "\u097F" for ch in all_text): issues.append("Devanagari/Hindi text detected")
    if FORBIDDEN_GAME_LANGUAGE.search(all_text): issues.append("A/B/countdown/game-show language detected")
    if SENSATIONAL_UNVERIFIED.search(all_text): issues.append("unsupported sensational wording detected")

    expected = [
        "pattern_interrupt", "tension", "mechanism", "transformation", "payoff", "loop"
    ] if content_mode == "viral" else [
        "hook", "context", "mechanism", "example", "exam_takeaway", "difference_card"
    ]
    actual = [getattr(s, "action_type", "") for s in scenes]
    if actual != expected: issues.append(f"scene roles must be {expected}, got {actual}")

    for i, scene in enumerate(scenes, start=1):
        if not scene.narration.strip(): issues.append(f"scene {i}: empty narration")
        if not scene.image_prompt.strip(): issues.append(f"scene {i}: missing image prompt")
        if len(scene.on_screen_text.split()) > 8: issues.append(f"scene {i}: on-screen text too long")
        if len(scene.card_points) > 1: issues.append(f"scene {i}: too many memory anchors")
        lower = scene.narration.lower()
        if any(f in lower for f in GENERIC_FILLERS): issues.append(f"scene {i}: generic filler")
        if scene.action_type in (("mechanism", "transformation") if content_mode == "viral" else ("mechanism", "example")) and len(scene.narration.split()) < 8:
            issues.append(f"scene {i}: teaching scene is too thin")

    return QAResult(ok=not issues, issues=issues)
