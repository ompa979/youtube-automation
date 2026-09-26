"""Natural Indian TTS with resilient free-provider fallbacks.

Preferred chain when configured:
1) Microsoft Edge/Azure voice via edge-tts
2) gTTS
3) local eSpeak

No Google Cloud TTS dependency is required.

The script can keep Roman Hinglish for captions while supplying a Devanagari-
optimized `tts_text` for Hindi-capable voices, improving pronunciation without
changing what the viewer reads.
"""
from __future__ import annotations

import asyncio
import json
import os
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
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n"
        "WrapStyle: 2\nScaledBorderAndShadow: yes\n\n[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour,"
        " Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow,"
        " Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Cap,Inter,78,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,2,2,60,60,220,1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    lines: list[str] = []
    for i in range(0, len(words), 4):
        chunk = words[i:i + 4]
        start, end = chunk[0][0], chunk[-1][1]
        text = re.sub(r"\s+", " ", " ".join(w[2] for w in chunk)).strip()
        text = text.replace("{", "(").replace("}", ")")
        lines.append(f"Dialogue: 0,{_ass_timestamp(start)},{_ass_timestamp(end)},Cap,,0,0,0,,{text}")
    out_path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")


def _audio_duration(path: Path) -> float | None:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, check=True, timeout=20,
        )
        value = float(result.stdout.strip())
        return value if value > 0 else None
    except Exception:
        return None


def _estimated_words(text: str) -> list[str]:
    return re.findall(r"\S+", text.strip())


def _write_estimated_ass(display_text: str, duration: float, ass_path: Path, overlay_text: str = "") -> None:
    words = _estimated_words(display_text)
    if not words:
        _write_ass([], ass_path)
        return
    # Slightly longer weighting for punctuation makes captions feel less rushed.
    weights = [1.35 if re.search(r"[.!?]$", w) else 1.0 for w in words]
    total = sum(weights)
    cursor = 0.0
    timed: list[tuple[float, float, str]] = []
    for word, weight in zip(words, weights):
        step = duration * weight / total
        timed.append((cursor, min(duration, cursor + step), word))
        cursor += step
    _write_ass(timed, ass_path)
    if overlay_text.strip():
        existing = ass_path.read_text(encoding="utf-8")
        overlay = f"Dialogue: 1,0:00:00.00,{_ass_timestamp(min(duration, 3.0))},Cap,,0,0,0,,{overlay_text.strip().replace("{", "(").replace("}", ")")}\n"
        ass_path.write_text(existing + overlay, encoding="utf-8")


async def _synth_edge(text: str, voice: str, audio_path: Path, ass_path: Path) -> float:
    communicate = edge_tts.Communicate(text, voice)
    words: list[tuple[float, float, str]] = []
    with open(audio_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 10_000_000
                dur = chunk["duration"] / 10_000_000
                words.append((start, start + dur, chunk["text"]))
    if not audio_path.exists() or audio_path.stat().st_size == 0:
        raise RuntimeError("Edge TTS returned no audio")
    duration = _audio_duration(audio_path)
    if not duration:
        raise RuntimeError("Edge TTS returned invalid duration")
    _write_ass(words, ass_path) if words else _write_estimated_ass(text, duration, ass_path)
    return duration


def _edge_voice_candidates(default_voice: str) -> list[str]:
    """Return configured Indian voices in preferred order, de-duplicated."""
    raw = os.getenv("TTS_VOICE") or os.getenv("EDGE_TTS_VOICE") or default_voice or "hi-IN-SwaraNeural"
    candidates = [x.strip() for x in raw.split(",") if x.strip()]
    # Keep a second Indian Hindi voice as a provider-level fallback.
    for voice in ("hi-IN-SwaraNeural", "hi-IN-MadhurNeural"):
        if voice not in candidates:
            candidates.append(voice)
    return candidates


def _synth_edge_candidates(text: str, default_voice: str, audio_path: Path, ass_path: Path) -> float:
    errors: list[str] = []
    for voice in _edge_voice_candidates(default_voice):
        try:
            print(f"[tts] edge voice={voice}")
            return asyncio.run(_synth_edge(text, voice, audio_path, ass_path))
        except Exception as exc:
            errors.append(f"{voice}: {exc}")
            audio_path.unlink(missing_ok=True)
            ass_path.unlink(missing_ok=True)
            print(f"[tts] edge voice {voice} failed: {exc}")
    raise RuntimeError("All Edge Hindi voices failed: " + " | ".join(errors))


def _gtts_language(voice: str) -> str:
    base = (voice or "hi").lower().split("-")[0]
    return {"en": "en", "hi": "hi", "es": "es", "fr": "fr", "de": "de"}.get(base, "hi")


def _synth_gtts(text: str, voice: str, audio_path: Path, ass_path: Path) -> float:
    from gtts import gTTS
    lang = _gtts_language(voice)
    gTTS(text=text, lang=lang, slow=False).save(str(audio_path))
    if not audio_path.exists() or audio_path.stat().st_size == 0:
        raise RuntimeError("gTTS returned no audio")
    duration = _audio_duration(audio_path) or max(1.0, len(_estimated_words(text)) / 2.4)
    _write_estimated_ass(text, duration, ass_path)
    return duration


def _synth_espeak(text: str, voice: str, audio_path: Path, ass_path: Path) -> float:
    exe = shutil.which("espeak-ng") or shutil.which("espeak")
    ffmpeg = shutil.which("ffmpeg")
    if not exe or not ffmpeg:
        raise RuntimeError("Neither espeak/espeak-ng nor ffmpeg is available")
    wav_path = audio_path.with_suffix(".wav")
    subprocess.run([exe, "-v", "hi", "-w", str(wav_path), text], check=True, timeout=60)
    subprocess.run([ffmpeg, "-y", "-i", str(wav_path), "-codec:a", "libmp3lame", "-q:a", "4", str(audio_path)], check=True, capture_output=True, timeout=60)
    wav_path.unlink(missing_ok=True)
    duration = _audio_duration(audio_path) or max(1.0, len(_estimated_words(text)) / 2.2)
    _write_estimated_ass(text, duration, ass_path)
    return duration


def _truthy_env(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def synthesize_scene(scene_index: int, display_text: str, tts_text: str, voice: str, on_screen_text: str = "") -> tuple[Path, Path, float]:
    audio_path = WORK_DIR / f"scene_{scene_index:02d}.mp3"
    ass_path = WORK_DIR / f"scene_{scene_index:02d}.ass"
    errors: list[str] = []

    provider_setting = os.getenv("TTS_PROVIDER", "edge").strip().lower()
    if provider_setting in {"auto", "automatic"}:
        providers = ["edge", "gtts", "espeak"]
    else:
        providers = [provider_setting]
        # Always keep free fallbacks available unless explicitly disabled.
        if _truthy_env(os.getenv("TTS_NO_FALLBACK"), False) is False:
            for fallback in ("edge", "gtts", "espeak"):
                if fallback not in providers:
                    providers.append(fallback)

    for provider in providers:
        try:
            if provider == "edge":
                edge_voice = os.getenv("TTS_VOICE") or os.getenv("EDGE_TTS_VOICE") or voice or "hi-IN-SwaraNeural"
                duration = _synth_edge_candidates(tts_text, edge_voice, audio_path, ass_path)
            elif provider == "gtts":
                duration = _synth_gtts(tts_text, os.getenv("TTS_LANGUAGE", voice), audio_path, ass_path)
            elif provider == "espeak":
                duration = _synth_espeak(tts_text, os.getenv("TTS_LANGUAGE", "hi"), audio_path, ass_path)
            else:
                continue
            # Captions should show the viewer-facing Roman Hinglish.
            if provider == "edge":
                if on_screen_text.strip():
                    existing = ass_path.read_text(encoding="utf-8")
                    safe_overlay = on_screen_text.strip().replace("{", "(").replace("}", ")")
                    overlay = (
                        "Dialogue: 1,0:00:00.00,"
                        f"{_ass_timestamp(min(duration, 3.0))},Cap,,0,0,0,,{safe_overlay}\n"
                    )
                    ass_path.write_text(existing + overlay, encoding="utf-8")
            else:
                _write_estimated_ass(display_text, duration, ass_path, on_screen_text)
            print(f"[tts] provider={provider}")
            return audio_path, ass_path, duration
        except Exception as exc:
            errors.append(f"{provider}: {exc}")
            audio_path.unlink(missing_ok=True)
            ass_path.unlink(missing_ok=True)
            print(f"[tts] {provider} failed: {exc}")

    raise RuntimeError("All TTS providers failed: " + " | ".join(errors))
