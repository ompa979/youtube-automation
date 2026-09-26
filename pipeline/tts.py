
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from pathlib import Path

try:
    import edge_tts
except ImportError:
    edge_tts = None

try:
    from gtts import gTTS
except ImportError:
    gTTS = None


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TTS_PROVIDER = os.getenv("TTS_PROVIDER", "edge").strip().lower()
TTS_LANGUAGE = os.getenv("TTS_LANGUAGE", "hi-IN").strip()

TTS_VOICE = os.getenv(
    "TTS_VOICE",
    "hi-IN-MadhurNeural,hi-IN-SwaraNeural",
).strip()

TTS_NO_FALLBACK = (
    os.getenv("TTS_NO_FALLBACK", "false").strip().lower()
    in {"1", "true", "yes", "on"}
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _timestamp(seconds: float) -> str:
    seconds = max(0.0, float(seconds))

    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60

    whole = int(secs)
    centiseconds = int(round((secs - whole) * 100))

    if centiseconds >= 100:
        whole += 1
        centiseconds = 0

    if whole >= 60:
        minutes += 1
        whole = 0

    if minutes >= 60:
        hours += 1
        minutes = 0

    return f"{hours}:{minutes:02d}:{whole:02d}.{centiseconds:02d}"


def _ass_timestamp(seconds: float) -> str:
    """
    ASS timestamps use H:MM:SS.cc.
    """
    return _timestamp(seconds)


def _safe_text(text: str) -> str:
    """
    Keep ASS dialogue safe from braces and line breaks.
    """
    return (
        str(text or "")
        .replace("{", "(")
        .replace("}", ")")
        .replace("\r", " ")
        .replace("\n", " ")
        .strip()
    )


def _voice_candidates() -> list[str]:
    """
    Read comma-separated voices while preserving configured order.
    """
    voices = [
        value.strip()
        for value in TTS_VOICE.split(",")
        if value.strip()
    ]

    if not voices:
        voices = [
            "hi-IN-MadhurNeural",
            "hi-IN-SwaraNeural",
        ]

    # Remove duplicates while preserving order.
    return list(dict.fromkeys(voices))


def _edge_voice_for_language() -> list[str]:
    voices = _voice_candidates()

    if TTS_LANGUAGE.lower().startswith("hi"):
        defaults = [
            "hi-IN-MadhurNeural",
            "hi-IN-SwaraNeural",
        ]
    else:
        defaults = voices

    result = []

    for voice in voices + defaults:
        if voice not in result:
            result.append(voice)

    return result


def _estimate_duration(text: str) -> float:
    """
    Conservative duration estimate used only if the TTS backend doesn't
    provide a duration measurement.
    """
    words = max(1, len(str(text or "").split()))

    # Natural Hindi/Hinglish speech is generally slower than raw English
    # token counting suggests.
    duration = words / 2.35

    return max(1.5, duration)


def _caption_segments(text: str, duration: float) -> list[tuple[float, float, str]]:
    """Create natural subtitle chunks from the spoken text.

    Captions are split on punctuation/phrases, not fixed seconds. Their timing
    is proportional to word count so the spoken content remains intact.
    """
    import re

    clean = _safe_text(text)
    if not clean:
        return []

    # Prefer natural sentence/phrase boundaries.
    pieces = [x.strip() for x in re.split(r"(?<=[.!?।,:;])\s+", clean) if x.strip()]

    # Keep captions readable on a 1080x1920 Short. Long phrases are wrapped
    # by words, never by dropping content.
    chunks: list[str] = []
    for piece in pieces:
        words = piece.split()
        if len(words) <= 10:
            chunks.append(piece)
            continue
        for i in range(0, len(words), 10):
            chunks.append(" ".join(words[i:i + 10]))

    if not chunks:
        chunks = [clean]

    total_words = sum(max(1, len(c.split())) for c in chunks)
    usable_duration = max(float(duration), 0.5)
    result: list[tuple[float, float, str]] = []
    cursor = 0.0

    for index, chunk in enumerate(chunks):
        weight = max(1, len(chunk.split())) / total_words
        segment_duration = usable_duration * weight

        # Avoid extremely fast flashes for tiny punctuation fragments while
        # preserving the full scene duration.
        if index < len(chunks) - 1:
            segment_duration = max(segment_duration, 0.85)

        end = usable_duration if index == len(chunks) - 1 else min(
            usable_duration, cursor + segment_duration
        )

        if end > cursor:
            result.append((cursor, end, chunk))
            cursor = end

    return result


def _write_ass(
    ass_path: Path,
    duration: float,
    overlay_text: str,
) -> None:
    """Write centered subtitles containing the actual spoken narration."""
    segments = _caption_segments(overlay_text, duration)

    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Inter,72,&H00FFFFFF,&H00FFFFFF,&H00000000,&H99000000,-1,0,0,0,100,100,0,0,1,4,2,5,90,90,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines: list[str] = []
    for start, end, caption in segments:
        # ASS uses \N for an explicit line break. Keep captions visually
        # centered and readable without removing any spoken words.
        words = caption.split()
        if len(words) > 6:
            mid = len(words) // 2
            caption = " ".join(words[:mid]) + r"\N" + " ".join(words[mid:])

        safe_caption = _safe_text(caption).replace("\\N", r"\N")
        lines.append(
            "Dialogue: 1,"
            f"{_ass_timestamp(start)},"
            f"{_ass_timestamp(end)},Cap,,0,0,0,,{safe_caption}"
        )

    ass_path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Edge TTS
# ---------------------------------------------------------------------------

async def _edge_synth(
    text: str,
    voice: str,
    audio_path: Path,
) -> float:
    if edge_tts is None:
        raise RuntimeError("edge-tts is not installed")

    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
    )

    with audio_path.open("wb") as output:
        async for chunk in communicate.stream():
            if chunk.get("type") == "audio":
                output.write(chunk["data"])

    if not audio_path.exists() or audio_path.stat().st_size == 0:
        raise RuntimeError("Edge TTS produced no audio")

    duration = _probe_duration(audio_path)

    if duration <= 0:
        duration = _estimate_duration(text)

    return duration


# ---------------------------------------------------------------------------
# gTTS
# ---------------------------------------------------------------------------

def _gtts_synth(
    text: str,
    audio_path: Path,
) -> float:
    if gTTS is None:
        raise RuntimeError("gTTS is not installed")

    # gTTS uses language codes such as "hi".
    language = "hi" if TTS_LANGUAGE.lower().startswith("hi") else "en"

    tts = gTTS(
        text=text,
        lang=language,
        slow=False,
    )

    tts.save(str(audio_path))

    if not audio_path.exists() or audio_path.stat().st_size == 0:
        raise RuntimeError("gTTS produced no audio")

    duration = _probe_duration(audio_path)

    if duration <= 0:
        duration = _estimate_duration(text)

    return duration


# ---------------------------------------------------------------------------
# eSpeak fallback
# ---------------------------------------------------------------------------

def _espeak_synth(
    text: str,
    audio_path: Path,
) -> float:
    executable = shutil.which("espeak-ng") or shutil.which("espeak")

    if executable is None:
        raise RuntimeError("Neither espeak-ng nor espeak is installed")

    # Hindi voice if available; otherwise use the system default.
    language = "hi" if TTS_LANGUAGE.lower().startswith("hi") else "en"

    command = [
        executable,
        "-v",
        language,
        "-w",
        str(audio_path),
        text,
    ]

    completed = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    if completed.returncode != 0:
        raise RuntimeError(
            "eSpeak failed: "
            + (completed.stderr.strip() or "unknown error")
        )

    if not audio_path.exists() or audio_path.stat().st_size == 0:
        raise RuntimeError("eSpeak produced no audio")

    duration = _probe_duration(audio_path)

    if duration <= 0:
        duration = _estimate_duration(text)

    return duration


# ---------------------------------------------------------------------------
# Media utilities
# ---------------------------------------------------------------------------

def _probe_duration(path: Path) -> float:
    ffprobe = shutil.which("ffprobe")

    if ffprobe is None:
        return 0.0

    command = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]

    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )

        value = completed.stdout.strip()

        if not value:
            return 0.0

        return max(0.0, float(value))

    except (ValueError, OSError):
        return 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _provider_order() -> list[str]:
    """
    Free-only TTS provider order.

    Requested provider is tried first.
    Then automatic fallbacks are used unless disabled.
    """
    requested = TTS_PROVIDER or "edge"

    providers: list[str] = [requested]

    if not TTS_NO_FALLBACK:
        for provider in ("edge", "gtts", "espeak"):
            if provider not in providers:
                providers.append(provider)

    return providers


def synthesize_scene(
    text: str,
    voice: str | None,
    audio_path: str | Path,
    ass_path: str | Path,
    overlay_text: str | None = None,
) -> tuple[Path, Path, float]:
    """
    Synthesize one scene.

    Returns:
        (audio_path, ass_path, duration)
    """
    text = str(text or "").strip()

    if not text:
        raise ValueError("Cannot synthesize empty text")

    audio_path = Path(audio_path)
    ass_path = Path(ass_path)

    audio_path.parent.mkdir(parents=True, exist_ok=True)
    ass_path.parent.mkdir(parents=True, exist_ok=True)

    # Remove stale files from previous attempts.
    for path in (audio_path, ass_path):
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    errors: list[str] = []

    for provider in _provider_order():
        try:
            print(f"[tts] trying provider={provider}")

            if provider == "edge":
                voices = [voice] if voice else _edge_voice_for_language()

                # If a single voice was explicitly supplied, still make sure
                # the configured Hindi fallback voices are available.
                if not TTS_NO_FALLBACK:
                    for candidate in _edge_voice_for_language():
                        if candidate not in voices:
                            voices.append(candidate)

                last_error: Exception | None = None

                for edge_voice in voices:
                    try:
                        print(f"[tts] edge voice={edge_voice}")

                        duration = asyncio.run(
                            _edge_synth(
                                text,
                                edge_voice,
                                audio_path,
                            )
                        )

                        print(
                            f"[tts] success provider=edge "
                            f"voice={edge_voice} duration={duration:.2f}s"
                        )

                        _write_ass(
                            ass_path,
                            duration,
                            overlay_text or "",
                        )

                        return audio_path, ass_path, duration

                    except Exception as exc:
                        last_error = exc
                        print(
                            f"[tts] edge voice={edge_voice} failed: "
                            f"{type(exc).__name__}: {exc}"
                        )

                        try:
                            audio_path.unlink()
                        except FileNotFoundError:
                            pass

                if last_error is not None:
                    raise last_error

                raise RuntimeError("No Edge TTS voices available")

            elif provider == "gtts":
                duration = _gtts_synth(
                    text,
                    audio_path,
                )

                print(
                    f"[tts] success provider=gtts "
                    f"duration={duration:.2f}s"
                )

                _write_ass(
                    ass_path,
                    duration,
                    overlay_text or "",
                )

                return audio_path, ass_path, duration

            elif provider in {"espeak", "espeak-ng"}:
                duration = _espeak_synth(
                    text,
                    audio_path,
                )

                print(
                    f"[tts] success provider=espeak "
                    f"duration={duration:.2f}s"
                )

                _write_ass(
                    ass_path,
                    duration,
                    overlay_text or "",
                )

                return audio_path, ass_path, duration

            else:
                raise RuntimeError(
                    f"Unknown TTS_PROVIDER: {provider}"
                )

        except Exception as exc:
            message = f"{provider}: {type(exc).__name__}: {exc}"
            errors.append(message)

            print(f"[tts] provider failed: {message}")

            try:
                audio_path.unlink()
            except FileNotFoundError:
                pass

            try:
                ass_path.unlink()
            except FileNotFoundError:
                pass

    raise RuntimeError(
        "All TTS providers failed: " + "; ".join(errors)
    )

