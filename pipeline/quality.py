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

# ─────────────────────────────────────────────────────────────────────────────
# V20 FEED-NATIVE PRE-UPLOAD QUALITY GATE
# ─────────────────────────────────────────────────────────────────────────────
from dataclasses import dataclass as _V20Dataclass
from pathlib import Path as _V20Path

@_V20Dataclass
class V20QualityResult:
    ok: bool
    issues: list[str]
    hard_cuts: int = 0
    mean_motion: float = 0.0
    loop_error: float | None = None


def verify_v20_quality(video_path: str | _V20Path, format_type: str) -> V20QualityResult:
    """Verify V20 creative invariants before upload.

    This deliberately checks more than container validity: single-canvas formats
    may not contain slideshow-style hard cuts; satisfying must contain genuine
    motion; micro-loops must return close to their opening frame; all V20 videos
    must be vertical 1080x1920, have audio, and stay within the intended duration.
    """
    import subprocess as _subprocess
    import cv2 as _cv2
    import numpy as _np

    W, H = 1080, 1920
    path = str(video_path)
    issues: list[str] = []
    cap = _cv2.VideoCapture(path)
    if not cap.isOpened():
        return V20QualityResult(False, ["video could not be opened"])

    fps = float(cap.get(_cv2.CAP_PROP_FPS) or 0)
    total_frames = int(cap.get(_cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(_cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(_cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    duration = total_frames / fps if fps > 0 else 0
    audio_probe = _subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_name", "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True,
    )
    has_audio = bool(audio_probe.stdout.strip())

    if (width, height) != (W, H): issues.append(f"resolution {width}x{height} != 1080x1920")
    if fps < 29: issues.append(f"fps too low: {fps:.2f}")
    if duration < 5.5 or duration > 9.5: issues.append(f"duration out of V20 range: {duration:.2f}s")
    if not has_audio: issues.append("missing audio stream")

    prev = None
    first = None
    last = None
    hard_cuts = 0
    motion_values: list[float] = []
    sample_step = max(1, total_frames // 240)
    i = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        gray = _cv2.cvtColor(frame, _cv2.COLOR_BGR2GRAY)
        if first is None:
            first = gray.copy()
        last = gray
        if prev is not None:
            diff = _cv2.absdiff(prev, gray)
            non_zero_ratio = float(_np.count_nonzero(diff > 40)) / float(diff.size)
            if non_zero_ratio > 0.45:
                hard_cuts += 1
            if i % sample_step == 0:
                motion_values.append(float(_np.mean(diff)))
        prev = gray
        i += 1
    cap.release()

    mean_motion = float(_np.mean(motion_values)) if motion_values else 0.0
    loop_error = None
    if first is not None and last is not None:
        loop_error = float(_np.mean(_cv2.absdiff(first, last)))

    if format_type in {"BRAIN_TRAP", "OPTICAL_ILLUSION", "INTERACTIVE_CHOICE", "MICRO_LOOP"} and hard_cuts > 1:
        issues.append(f"single-canvas format contains {hard_cuts} hard cuts")
    if format_type == "MICRO_LOOP" and (loop_error is None or loop_error > 25.0):
        issues.append(f"micro-loop seam error too high: {loop_error}")
    if format_type == "SATISFYING" and mean_motion < 1.5:
        issues.append(f"satisfying source has insufficient real motion: {mean_motion:.2f}")

    return V20QualityResult(not issues, issues, hard_cuts, mean_motion, loop_error)


def assert_v20_quality(video_path: str | _V20Path, format_type: str) -> V20QualityResult:
    result = verify_v20_quality(video_path, format_type)
    if not result.ok:
        raise RuntimeError("V20 QA REJECTED: " + " | ".join(result.issues))
    print(f"[v20-qa] PASS format={format_type} cuts={result.hard_cuts} motion={result.mean_motion:.2f} seam={result.loop_error}")
    return result
