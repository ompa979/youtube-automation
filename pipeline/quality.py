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
# V20 FEED-NATIVE PRE-UPLOAD QUALITY GATE — EXTREME / FAIL-CLOSED
# ─────────────────────────────────────────────────────────────────────────────
from dataclasses import dataclass as _V20Dataclass
from pathlib import Path as _V20Path

_V20_FORMATS = {"BRAIN_TRAP", "OPTICAL_ILLUSION", "SATISFYING", "MICRO_LOOP", "INTERACTIVE_CHOICE"}
_V20_CANVAS_FORMATS = {"BRAIN_TRAP", "OPTICAL_ILLUSION", "MICRO_LOOP", "INTERACTIVE_CHOICE"}
_V20_EXPECTED_DURATION = {
    "BRAIN_TRAP": 8.0,
    "OPTICAL_ILLUSION": 8.0,
    "SATISFYING": 7.0,
    "MICRO_LOOP": 7.0,
    "INTERACTIVE_CHOICE": 8.0,
}

@_V20Dataclass
class V20QualityResult:
    ok: bool
    issues: list[str]
    hard_cuts: int = 0
    mean_motion: float = 0.0
    loop_error: float | None = None
    active_motion_ratio: float = 0.0
    tail_motion: float = 0.0
    p10_motion: float = 0.0
    max_freeze_frames: int = 0
    dark_frame_ratio: float = 0.0
    audio_mean_db: float | None = None


def verify_v20_spec(spec: dict[str, Any]) -> list[str]:
    """Fail-closed validation of the creative contract before rendering."""
    issues: list[str] = []
    fmt = str(spec.get("format", ""))
    if fmt not in _V20_FORMATS:
        issues.append(f"unsupported V20 format: {fmt!r}")
        return issues

    if str(spec.get("distribution_goal")) != "SHORTS_FEED":
        issues.append("distribution goal must be SHORTS_FEED")
    if spec.get("search_intent") is not False:
        issues.append("search_intent must be false")
    if str(spec.get("source_contract")) == "MULTI_SCENE":
        issues.append("multi-scene source contract forbidden")
    if fmt in _V20_CANVAS_FORMATS and spec.get("source_contract") != "SINGLE_CANVAS":
        issues.append(f"{fmt} requires SINGLE_CANVAS source contract")
    if fmt == "SATISFYING" and spec.get("source_contract") != "REAL_MOTION_VIDEO":
        issues.append("SATISFYING requires REAL_MOTION_VIDEO source contract")
    if not str(spec.get("hook_text", "")).strip():
        issues.append("missing frame-zero hook")

    expected = _V20_EXPECTED_DURATION[fmt]
    try:
        duration = float(spec.get("duration_seconds"))
        if abs(duration - expected) > 0.25:
            issues.append(f"duration contract mismatch: {duration:.2f}s vs {expected:.2f}s")
    except (TypeError, ValueError):
        issues.append("invalid duration_seconds")

    if fmt == "BRAIN_TRAP":
        if spec.get("reveal_strategy") == "PUNCH_ZOOM_TARGET":
            target = spec.get("target_point")
            if not isinstance(target, dict):
                issues.append("PUNCH_ZOOM_TARGET requires target_point")
            else:
                try:
                    x, y = float(target["x"]), float(target["y"])
                    if not (0.08 <= x <= 0.92 and 0.12 <= y <= 0.70):
                        issues.append(f"target outside safe creative region: ({x:.3f},{y:.3f})")
                    if abs(x - 0.50) < 0.12 and abs(y - 0.50) < 0.12:
                        issues.append("target is too close to visual center")
                except (KeyError, TypeError, ValueError):
                    issues.append("invalid target_point")
        elif spec.get("reveal_strategy") != "FULL_FRAME_PULSE":
            issues.append("Brain Trap has no approved reveal strategy")

    # V20 must never depend on a guessed bounding box for an AI-generated image.
    prompt = str(spec.get("visual_prompt", "")).lower()
    forbidden = ("bounding box", "bounding-box", "draw a circle around", "red circle around", "target circle")
    if any(x in prompt for x in forbidden):
        issues.append("visual prompt contains hardcoded overlay-target instructions")
    return issues


def _ffprobe_json(path: str) -> dict[str, Any]:
    import json as _json
    import subprocess as _subprocess
    p = _subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
        capture_output=True, text=True,
    )
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip() or "ffprobe failed")
    return _json.loads(p.stdout or "{}")


def _audio_mean_db(path: str) -> float | None:
    import re as _re
    import subprocess as _subprocess
    p = _subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    m = _re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB", p.stderr)
    return float(m.group(1)) if m else None


def _max_true_run(values: list[bool]) -> int:
    best = cur = 0
    for value in values:
        cur = cur + 1 if value else 0
        best = max(best, cur)
    return best


def verify_v20_quality(video_path: str | _V20Path, format_type: str) -> V20QualityResult:
    """Adversarial V20 viewer-experience gate.

    FAIL-CLOSED PRINCIPLE:
    A file is rejected when it is merely technically valid but visually stagnant,
    frozen, blank, cut-heavy, badly encoded, silent, or outside the declared
    format contract. Overlay animation cannot manufacture creative motion because
    motion is measured inside the protected creative ROI.
    """
    import subprocess as _subprocess
    import cv2 as _cv2
    import numpy as _np

    W, H, FPS = 1080, 1920, 30.0
    path = str(video_path)
    issues: list[str] = []
    if format_type not in _V20_FORMATS:
        return V20QualityResult(False, [f"unsupported V20 format: {format_type}"])
    if not _V20Path(path).exists() or _V20Path(path).stat().st_size == 0:
        return V20QualityResult(False, ["video missing or empty"])

    try:
        probe = _ffprobe_json(path)
    except Exception as exc:
        return V20QualityResult(False, [f"ffprobe failed: {exc}"])
    streams = probe.get("streams") or []
    vstreams = [s for s in streams if s.get("codec_type") == "video"]
    astreams = [s for s in streams if s.get("codec_type") == "audio"]
    if len(vstreams) != 1:
        issues.append(f"expected exactly one video stream, got {len(vstreams)}")
    if len(astreams) != 1:
        issues.append(f"expected exactly one audio stream, got {len(astreams)}")
    v = vstreams[0] if vstreams else {}
    width, height = int(v.get("width") or 0), int(v.get("height") or 0)
    if (width, height) != (W, H):
        issues.append(f"resolution {width}x{height} != 1080x1920")
    try:
        num, den = (v.get("r_frame_rate") or "0/1").split("/")
        fps = float(num) / float(den)
    except Exception:
        fps = 0.0
    if not 29.5 <= fps <= 30.5:
        issues.append(f"fps outside strict V20 range: {fps:.3f}")

    try:
        duration = float((probe.get("format") or {}).get("duration") or v.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    expected = _V20_EXPECTED_DURATION[format_type]
    if abs(duration - expected) > 0.15:
        issues.append(f"duration {duration:.3f}s outside strict {expected:.2f}±0.15s contract")

    audio_mean = _audio_mean_db(path) if astreams else None
    if audio_mean is None:
        issues.append("audio level could not be measured")
    elif audio_mean < -45.0:
        issues.append(f"audio effectively silent: mean_volume={audio_mean:.1f}dB")

    cap = _cv2.VideoCapture(path)
    if not cap.isOpened():
        issues.append("OpenCV could not decode video")
        return V20QualityResult(False, issues)
    total_frames = int(cap.get(_cv2.CAP_PROP_FRAME_COUNT) or 0)
    decoded = 0
    prev = first = last = None
    motion: list[float] = []
    hard_cuts = 0
    dark = 0
    near_white = 0
    freeze_flags: list[bool] = []
    frame_means: list[float] = []

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        decoded += 1
        gray = _cv2.cvtColor(frame, _cv2.COLOR_BGR2GRAY)
        if first is None:
            first = gray.copy()
        last = gray
        mean_luma = float(_np.mean(gray))
        frame_means.append(mean_luma)
        if mean_luma < 4.0:
            dark += 1
        if mean_luma > 251.0:
            near_white += 1
        if prev is not None:
            diff = _cv2.absdiff(prev, gray)
            # Hard-cut detector: require a genuinely scene-wide discontinuity.
            # This deliberately ignores the renderer's one-frame full-canvas payoff
            # pulse and normal punch-zoom motion, which are not scene cuts.
            nz = float(_np.count_nonzero(diff > 40)) / float(diff.size)
            mean_delta = float(_np.mean(diff))
            if nz > 0.60 and mean_delta > 18.0:
                hard_cuts += 1

            h, w = gray.shape
            # Protected creative ROI: exclude top 12% and bottom 18%, plus side margins.
            y0, y1 = int(h * 0.12), int(h * 0.82)
            x0, x1 = int(w * 0.05), int(w * 0.95)
            roi = diff[y0:y1, x0:x1]
            roi_small = _cv2.resize(roi, (180, 280), interpolation=_cv2.INTER_AREA)
            m = float(_np.mean(roi_small))
            motion.append(m)
            freeze_flags.append(m < 0.35)
        prev = gray
    cap.release()

    if decoded != total_frames and abs(decoded - total_frames) > 1:
        issues.append(f"decode integrity mismatch: probed={total_frames}, decoded={decoded}")
    if decoded < int(expected * FPS * 0.98):
        issues.append(f"too few decodable frames: {decoded}")
    if not motion:
        issues.append("no inter-frame motion samples available")

    arr = _np.asarray(motion, dtype=float) if motion else _np.asarray([0.0])
    mean_motion = float(_np.mean(arr))
    p10 = float(_np.percentile(arr, 10))
    p25 = float(_np.percentile(arr, 25))
    active_ratio = float(_np.mean(arr >= 0.35))
    first_window = arr[:max(1, int(len(arr) * 0.10))]
    tail = arr[int(len(arr) * 0.80):] if len(arr) > 5 else arr
    tail_motion = float(_np.mean(tail))
    max_freeze = _max_true_run(freeze_flags)
    dark_ratio = dark / max(1, decoded)
    white_ratio = near_white / max(1, decoded)

    if hard_cuts > 0:
        issues.append(f"hard scene cuts detected: {hard_cuts}; V20 is cut-free")
    if dark_ratio > 0.02:
        issues.append(f"excessive near-black frames: {dark_ratio:.2%}")
    if white_ratio > 0.02:
        issues.append(f"excessive near-white frames: {white_ratio:.2%}")

    if format_type in _V20_CANVAS_FORMATS:
        # Extremely strict: motion must be persistent, not a short zoom followed by
        # a frozen hold. Thresholds are intentionally far above the old gate.
        if mean_motion < 1.25:
            if mean_motion < 0.10:
                issues.append(f"creative canvas is effectively static: motion={mean_motion:.2f}")
            else:
                issues.append(f"creative motion too weak: mean={mean_motion:.2f} < 1.25")
        if p10 < 0.50:
            issues.append(f"creative motion too intermittent: p10={p10:.2f} < 0.50")
        if p25 < 1.00:
            issues.append(f"creative motion distribution too weak: p25={p25:.2f} < 1.00")
        if active_ratio < 0.95:
            issues.append(f"creative motion continuity failed: active={active_ratio:.2%} < 95%")
        if first_window.mean() < 0.75:
            issues.append(f"frame-0 hook lacks immediate movement: first10%={first_window.mean():.2f}")
        if tail_motion < max(0.75, mean_motion * 0.45):
            issues.append(f"creative motion decays too far in final 20%: tail={tail_motion:.2f}, overall={mean_motion:.2f}")
        if max_freeze > int(FPS * 0.20):
            issues.append(f"freeze run too long: {max_freeze} frames ({max_freeze/FPS:.2f}s)")

    if format_type == "SATISFYING":
        if mean_motion < 1.50:
            issues.append(f"real motion source insufficient: mean={mean_motion:.2f} < 1.50")
        if p10 < 0.35:
            issues.append(f"satisfying source has motion gaps: p10={p10:.2f} < 0.35")
        if max_freeze > int(FPS * 0.50):
            issues.append(f"real-motion source freezes too long: {max_freeze/FPS:.2f}s")

    loop_error = None
    if first is not None and last is not None:
        # Compare blurred luminance to avoid compression noise making a bad seam look good.
        a = _cv2.GaussianBlur(first, (9, 9), 0)
        b = _cv2.GaussianBlur(last, (9, 9), 0)
        loop_error = float(_np.mean(_cv2.absdiff(a, b)))
    if format_type == "MICRO_LOOP":
        if loop_error is None or loop_error > 18.0:
            issues.append(f"micro-loop seam error too high: {loop_error}")

    return V20QualityResult(
        not issues, issues, hard_cuts, mean_motion, loop_error,
        active_ratio, tail_motion, p10, max_freeze, dark_ratio, audio_mean,
    )


def assert_v20_quality(video_path: str | _V20Path, format_type: str) -> V20QualityResult:
    result = verify_v20_quality(video_path, format_type)
    if not result.ok:
        raise RuntimeError("V20 EXTREME QA REJECTED: " + " | ".join(result.issues))
    print(
        f"[v20-extreme-qa] PASS format={format_type} cuts={result.hard_cuts} "
        f"motion={result.mean_motion:.2f} p10={result.p10_motion:.2f} "
        f"active={result.active_motion_ratio:.1%} tail={result.tail_motion:.2f} "
        f"freeze={result.max_freeze_frames}f audio={result.audio_mean_db:.1f}dB"
    )
    return result
