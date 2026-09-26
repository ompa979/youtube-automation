"""Text-to-speech via edge-tts. Also emits a word-timed ASS subtitle file."""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

import edge_tts

from .config import WORK_DIR

def _ass_timestamp(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:d}:{m:02d}:{s:05.2f}"

def _write_ass(words: list[tuple[float, float, str]], out_path: Path) -> None:
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 1080\n"
        "PlayResY: 1920\n"
        "WrapStyle: 2\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour,"
        " Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow,"
        " Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Cap,Inter,86,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,"
        "-1,0,0,0,100,100,0,0,1,4,2,2,60,60,220,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    lines: list[str] = []
    window = 3
    for i in range(len(words)):
        chunk = words[i:i + window]
        if not chunk:
            continue
        start = chunk[0][0]
        end = chunk[-1][1]
        text = " ".join(w[2] for w in chunk).strip()
        text = re.sub(r"\s+", " ", text)
        text = text.replace("{", "(").replace("}", ")")
        lines.append(
            f"Dialogue: 0,{_ass_timestamp(start)},{_ass_timestamp(end)},Cap,,0,0,0,,{text}"
        )

    out_path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")

async def _synth(text: str, voice: str, audio_path: Path, ass_path: Path) -> float:
    communicate = edge_tts.Communicate(text, voice)

    words: list[tuple[float, float, str]] = []
    last_end = 0.0

    with open(audio_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 10_000_000
                dur = chunk["duration"] / 10_000_000
                words.append((start, start + dur, chunk["text"]))
                last_end = start + dur

    _write_ass(words, ass_path)
    return last_end

def synthesize_scene(scene_index: int, text: str, voice: str) -> tuple[Path, Path, float]:
    audio_path = WORK_DIR / f"scene_{scene_index:02d}.mp3"
    ass_path = WORK_DIR / f"scene_{scene_index:02d}.ass"
    duration = asyncio.run(_synth(text, voice, audio_path, ass_path))
    return audio_path, ass_path, duration
