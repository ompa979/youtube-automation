"""Word-by-word ASS karaoke captions.

Builds a libass .ass subtitle file that shows ONE bold word on screen at a
time, timed to real (edge-tts) or estimated (other providers) per-word
speech timing, with a quick scale-pop + fire-color-flash-to-white animation
on each word — the CapCut / Opus-Clip caption look, instead of the old
static full-sentence subtitle block.

Burned in via ffmpeg's `ass=` filter (libass), NOT by stacking one drawtext
filter per word — that stays fast and lets libass handle shaping/kerning
regardless of how many words a scene has.
"""
from __future__ import annotations

from pathlib import Path

W, H = 1080, 1920
_MIN_WORD_SECONDS = 0.12

# BGR hex (ASS color order is &HBBGGRR&), matching render.py's fire color
# 0xFF4A1F (RGB) and plain white.
_FIRE_ASS = "1F4AFF"
_WHITE_ASS = "FFFFFF"


def _fmt_ts(t: float) -> str:
    """ffmpeg/ASS timestamp: H:MM:SS.cc (centiseconds)."""
    t = max(0.0, t)
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t - h * 3600 - m * 60
    return f"{h:d}:{m:02d}:{s:05.2f}"


def _escape_word(word: str) -> str:
    # Strip characters that would break an ASS override block or line.
    return word.replace("\\", "").replace("{", "").replace("}", "").replace("\n", " ").strip()


def build_word_ass(
    word_timings: list[dict] | None,
    scene_duration: float,
    out_path: Path,
    fontname: str = "Inter",
) -> bool:
    """Writes an .ass file with one Dialogue line per word, each showing
    only during its [start, end) window. Returns False (and writes nothing)
    when there's no usable timing data, so the caller can fall back to the
    old block-subtitle renderer instead of shipping an empty caption track.
    """
    words = [w for w in (word_timings or []) if (w.get("word") or "").strip()]
    if not words:
        return False

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {W}\nPlayResY: {H}\n"
        "WrapStyle: 2\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Word,{fontname},92,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,"
        "-1,0,0,0,100,100,0,0,1,7,2,2,60,60,170,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    events: list[str] = []
    n = len(words)
    for i, w in enumerate(words):
        start = max(0.0, float(w.get("start", 0.0)))
        end = float(w.get("end", start + _MIN_WORD_SECONDS))
        if end - start < _MIN_WORD_SECONDS:
            end = start + _MIN_WORD_SECONDS
        # Never overlap the next word, never run past the scene.
        if i + 1 < n:
            next_start = max(0.0, float(words[i + 1].get("start", end)))
            end = min(end, next_start)
        if scene_duration > _MIN_WORD_SECONDS + 0.01:
            end = min(end, scene_duration - 0.01)
        if end <= start:
            continue
        text = _escape_word(str(w.get("word", "")))
        if not text:
            continue
        # Pop scale-in (55% -> 100% over 90ms) + fire-to-white color flash
        # (over 180ms), both relative to this Dialogue line's own start time.
        override = (
            r"{\an2\fscx55\fscy55\1c&H" + _FIRE_ASS + r"&"
            r"\t(0,90,\fscx100\fscy100)"
            r"\t(0,180,\1c&H" + _WHITE_ASS + r"&)}"
        )
        events.append(f"Dialogue: 0,{_fmt_ts(start)},{_fmt_ts(end)},Word,,0,0,0,,{override}{text}\n")

    if not events:
        return False

    out_path.write_text(header + "".join(events), encoding="utf-8")
    return True
