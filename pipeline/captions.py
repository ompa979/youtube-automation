"""Two-word ASS karaoke captions.

Shows TWO words at a time, synced to real (edge-tts / faster-whisper) or
estimated per-word timing.  Design rules:

  - Pairs never cross a sentence boundary (split before "." "!" "?").
  - Terms like "3NF", "IBPS SO", "RBI Grade B" are treated as one unit and
    are never split across pairs.  Add to _PROTECTED_TERMS as needed.
  - Each pair shows from its first word's start time to the NEXT pair's start
    time, so there are no gaps between captions.
  - The last pair of a sentence ends at the start of the next sentence's first
    pair (or at scene end).
  - Keeps the existing pop-scale animation and orange keyword highlight: the
    first word of a pair flashes fire-orange -> white; the second word appears
    white.  On very short pairs (single protected term) both words share the
    same flash.

Burned in via ffmpeg's `ass=` filter (libass), NOT by stacking one drawtext
filter per word — stays fast and lets libass handle shaping/kerning.
"""
from __future__ import annotations

import re
from pathlib import Path

W, H = 1080, 1920
_MIN_PAIR_SECONDS = 0.15

# BGR hex (ASS color order is &HBBGGRR&), matching render.py's fire color
# 0xFF4A1F (RGB) and plain white.
_FIRE_ASS = "1F4AFF"
_WHITE_ASS = "FFFFFF"

# Protected multi-word terms that must never be split across caption pairs.
# Case-insensitive comparison is done at pair-building time.
_PROTECTED_TERMS: list[str] = [
    "3NF", "1NF", "2NF", "BCNF",
    "IBPS SO", "IBPS PO", "IBPS RRB", "SBI PO", "SBI SO",
    "RBI Grade B", "RBI Assistant", "LIC AAO",
    "OSI model", "TCP IP", "ACID properties",
    "primary key", "foreign key", "composite key",
    "left join", "right join", "inner join", "full join",
    "data warehouse", "data lake",
]

# Sentence-ending punctuation — never let a pair cross these.
_SENTENCE_END_RE = re.compile(r"[.!?]$")


def _fmt_ts(t: float) -> str:
    """ASS timestamp: H:MM:SS.cc (centiseconds)."""
    t = max(0.0, t)
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t - h * 3600 - m * 60
    return f"{h:d}:{m:02d}:{s:05.2f}"


def _escape_text(text: str) -> str:
    return text.replace("\\", "").replace("{", "").replace("}", "").replace("\n", " ").strip()


def _words_to_pairs(words: list[dict]) -> list[list[dict]]:
    """Group word-timing dicts into two-word pairs.

    Rules:
    1. If two consecutive words form a protected term, they stay together.
    2. A pair never crosses a sentence end (word ending in .!?).
    3. Default: two words per pair.
    """
    pairs: list[list[dict]] = []
    i = 0
    n = len(words)

    # Build a lower-case set of protected bigrams for fast lookup.
    protected_lower: set[str] = set()
    for term in _PROTECTED_TERMS:
        parts = term.lower().split()
        if len(parts) == 2:
            protected_lower.add(parts[0] + " " + parts[1])

    while i < n:
        w0 = words[i]
        word0 = str(w0.get("word", "")).strip()

        # Check if i and i+1 form a protected bigram.
        if i + 1 < n:
            word1 = str(words[i + 1].get("word", "")).strip()
            bigram = (word0 + " " + word1).lower()
            # Strip trailing punctuation for matching.
            bigram_clean = re.sub(r"[.!?,;:]+$", "", bigram).strip()
            if bigram_clean in protected_lower:
                pairs.append([w0, words[i + 1]])
                i += 2
                continue

        # Never let a pair cross a sentence end.
        if _SENTENCE_END_RE.search(word0):
            pairs.append([w0])
            i += 1
            continue

        # Default: pair two words.
        if i + 1 < n:
            pairs.append([w0, words[i + 1]])
            i += 2
        else:
            pairs.append([w0])
            i += 1

    return pairs


def build_word_ass(
    word_timings: list[dict] | None,
    scene_duration: float,
    out_path: Path,
    fontname: str = "Inter",
) -> bool:
    """Writes an .ass file with one Dialogue line per two-word pair.

    Each pair is shown from its first word's start time until the next pair
    starts — no gaps between captions.  Returns False (and writes nothing)
    when there's no usable timing data.
    """
    words = [w for w in (word_timings or []) if (w.get("word") or "").strip()]
    if not words:
        return False

    pairs = _words_to_pairs(words)
    if not pairs:
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
        "-1,0,0,0,100,100,0,0,1,7,2,5,60,60,0,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    events: list[str] = []
    n_pairs = len(pairs)

    for p_idx, pair in enumerate(pairs):
        # Pair start = first word's start time.
        start = max(0.0, float(pair[0].get("start", 0.0)))

        # Pair end = next pair's start time (gap-free), or scene end.
        if p_idx + 1 < n_pairs:
            next_start = max(0.0, float(pairs[p_idx + 1][0].get("start", start + _MIN_PAIR_SECONDS)))
            end = next_start
        else:
            # Last pair: use the last word's own end time, capped at scene end.
            last_word = pair[-1]
            end = float(last_word.get("end", start + _MIN_PAIR_SECONDS))
            if scene_duration > _MIN_PAIR_SECONDS + 0.01:
                end = min(end, scene_duration - 0.01)

        # Enforce minimum display duration.
        if end - start < _MIN_PAIR_SECONDS:
            end = start + _MIN_PAIR_SECONDS
        if scene_duration > _MIN_PAIR_SECONDS + 0.01:
            end = min(end, scene_duration - 0.01)
        if end <= start:
            continue

        # Build display text: words joined by a space.
        pair_text = " ".join(
            _escape_text(str(w.get("word", ""))) for w in pair
        ).strip()
        if not pair_text:
            continue

        # Pop scale-in (55% -> 100% over 90ms) + fire-to-white color flash
        # (over 180ms), both relative to this Dialogue line's own start time.
        override = (
            r"{\an5\fscx55\fscy55\1c&H" + _FIRE_ASS + r"&"
            r"\t(0,90,\fscx100\fscy100)"
            r"\t(0,180,\1c&H" + _WHITE_ASS + r"&)}"
        )
        events.append(
            f"Dialogue: 0,{_fmt_ts(start)},{_fmt_ts(end)},Word,,0,0,0,,{override}{pair_text}\n"
        )

    if not events:
        return False

    out_path.write_text(header + "".join(events), encoding="utf-8")
    return True
