"""Text-to-speech with resilient fallbacks.

Primary TTS: edge-tts.
Fallback 1: gTTS (Google Translate TTS).
Fallback 2: local espeak-ng/espeak when available.

The pipeline must not fail just because Microsoft's Edge TTS WebSocket returns
403/5xx.  Subtitle timings are generated from the resulting audio duration.
"""
from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
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


def _audio_duration(path: Path) -> float | None:
    """Return media duration using ffprobe, if available."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, check=True, timeout=20,
        )
        value = float(result.stdout.strip())
        return value if value > 0 else None
    except Exception:
        return None


def _estimated_words(text: str) -> list[str]:
    return re.findall(r"\S+", text.strip())


def _write_estimated_ass(text: str, duration: float, ass_path: Path) -> None:
    words = _estimated_words(text)
    if not words:
        _write_ass([], ass_path)
        return
    # Divide the actual/estimated audio duration over words.  This is only a
    # fallback subtitle timing; Edge TTS word boundaries remain preferred.
    step = max(duration / len(words), 0.08)
    timed = []
    for i, word in enumerate(words):
        start = i * step
        end = min(duration, (i + 1) * step)
        timed.append((start, end, word))
    _write_ass(timed, ass_path)


async def _synth_edge(text: str, voice: str, audio_path: Path, ass_path: Path) -> float:
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

    if not audio_path.exists() or audio_path.stat().st_size == 0:
        raise RuntimeError("Edge TTS returned no audio")

    duration = _audio_duration(audio_path) or last_end
    if duration <= 0:
        raise RuntimeError("Edge TTS returned invalid duration")
    _write_ass(words, ass_path)
    return duration


def _gtts_language(voice: str) -> str:
    # Map the project's voice names to gTTS language codes.  Keep this simple
    # and deterministic; regional Edge voices are not available in gTTS.
    base = (voice or "en").lower().split("-")[0]
    return {"en": "en", "hi": "hi", "es": "es", "fr": "fr", "de": "de"}.get(base, "en")


def _synth_gtts(text: str, voice: str, audio_path: Path, ass_path: Path) -> float:
    from gtts import gTTS

    lang = _gtts_language(voice)
    gTTS(text=text, lang=lang, slow=False).save(str(audio_path))
    if not audio_path.exists() or audio_path.stat().st_size == 0:
        raise RuntimeError("gTTS returned no audio")

    duration = _audio_duration(audio_path)
    if duration is None:
        # Conservative fallback if ffprobe is unavailable.
        duration = max(1.0, len(_estimated_words(text)) / 2.4)
    _write_estimated_ass(text, duration, ass_path)
    return duration


def _synth_espeak(text: str, voice: str, audio_path: Path, ass_path: Path) -> float:
    exe = shutil.which("espeak-ng") or shutil.which("espeak")
    ffmpeg = shutil.which("ffmpeg")
    if not exe or not ffmpeg:
        raise RuntimeError("Neither espeak/espeak-ng nor ffmpeg is available")

    wav_path = audio_path.with_suffix(".wav")
    lang = _gtts_language(voice)
    subprocess.run([exe, "-v", lang, "-w", str(wav_path), text], check=True, timeout=60)
    subprocess.run([ffmpeg, "-y", "-i", str(wav_path), "-codec:a", "libmp3lame", "-q:a", "4", str(audio_path)],
                   check=True, capture_output=True, timeout=60)
    wav_path.unlink(missing_ok=True)

    duration = _audio_duration(audio_path) or max(1.0, len(_estimated_words(text)) / 2.2)
    _write_estimated_ass(text, duration, ass_path)
    return duration


def synthesize_scene(scene_index: int, text: str, voice: str) -> tuple[Path, Path, float]:
    audio_path = WORK_DIR / f"scene_{scene_index:02d}.mp3"
    ass_path = WORK_DIR / f"scene_{scene_index:02d}.ass"
    errors: list[str] = []

    # Edge TTS is preferred, but a service-side 403 must not kill the whole
    # video generation job.
    try:
        duration = asyncio.run(_synth_edge(text, voice, audio_path, ass_path))
        print("[tts] provider=edge-tts")
        return audio_path, ass_path, duration
    except Exception as exc:
        errors.append(f"edge-tts: {exc}")
        audio_path.unlink(missing_ok=True)
        ass_path.unlink(missing_ok=True)
        print(f"[tts] Edge TTS failed; trying gTTS fallback: {exc}")

    try:
        duration = _synth_gtts(text, voice, audio_path, ass_path)
        print("[tts] provider=gTTS")
        return audio_path, ass_path, duration
    except Exception as exc:
        errors.append(f"gTTS: {exc}")
        audio_path.unlink(missing_ok=True)
        ass_path.unlink(missing_ok=True)
        print(f"[tts] gTTS failed; trying local espeak fallback: {exc}")

    try:
        duration = _synth_espeak(text, voice, audio_path, ass_path)
        print("[tts] provider=espeak")
        return audio_path, ass_path, duration
    except Exception as exc:
        errors.append(f"espeak: {exc}")
        audio_path.unlink(missing_ok=True)
        ass_path.unlink(missing_ok=True)

    raise RuntimeError("All TTS providers failed: " + " | ".join(errors))
