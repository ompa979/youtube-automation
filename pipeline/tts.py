"""Indian-English narration backend for the YouTube Shorts pipeline.

Policy for V6:
- narration is English only
- no subtitles / ASS files are generated or rendered
- TTS_PROVIDER / TTS_VOICE / TTS_LANGUAGE secrets are now actually honoured.
  Previously this module hardcoded gTTS and ignored those env vars entirely.
- provider="edge" (default) uses Microsoft Edge neural voices via the
  edge-tts package, which sound far more natural than gTTS. Its public
  websocket endpoint occasionally returns 403 on GitHub-hosted runners, so
  we retry with backoff before giving up.
- provider="gtts" uses Google's free India endpoint (flat/robotic but
  reliable) as a fallback or explicit choice.
- espeak-ng en-in is the final offline fallback if both network TTS options
  fail.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import time
from pathlib import Path

try:
    from gtts import gTTS
except ImportError:
    gTTS = None

try:
    import edge_tts
except ImportError:
    edge_tts = None

import requests


# Real defaults now, not just placeholders: these are only used if the
# TTS_PROVIDER / TTS_VOICE / TTS_LANGUAGE secrets are not set.
# Valid values: "edge" (Microsoft Edge neural voices, default), "openrouter"
# (OpenRouter's /v1/audio/speech endpoint — reuses OPENROUTER_API_KEY, no
# separate service), "gtts" (flat/robotic but never blocked).
TTS_PROVIDER = os.getenv("TTS_PROVIDER", "edge").strip().lower() or "edge"
TTS_LANGUAGE = os.getenv("TTS_LANGUAGE", "en-IN").strip() or "en-IN"
# Model used when TTS_PROVIDER=openrouter. Set OPENROUTER_TTS_MODEL to
# override, e.g. "deepgram/flux-tts:free" or "fish-audio/s2.1-pro:free".
# Grab the exact id from https://openrouter.ai/models?output_modalities=speech
OPENROUTER_TTS_MODEL = os.getenv("OPENROUTER_TTS_MODEL", "deepgram/flux-tts:free").strip()
OPENROUTER_TTS_ENDPOINT = os.getenv("OPENROUTER_TTS_ENDPOINT", "https://openrouter.ai/api/v1/audio/speech")

_VOICE_DEFAULTS = {
    # en-IN-NeerjaNeural / en-IN-PrabhatNeural are real Microsoft Edge Indian
    # English neural voices. Set TTS_VOICE to switch (e.g. to PrabhatNeural
    # for a male voice, or any other Edge voice name).
    "edge": "en-IN-NeerjaNeural",
    # "alloy" is the OpenAI-style default most OpenRouter TTS providers
    # accept; check the model's supported_voices list for exact IDs.
    "openrouter": "alloy",
    "gtts": "en-IN",
}
_default_voice = _VOICE_DEFAULTS.get(TTS_PROVIDER, "en-IN")
TTS_VOICE = os.getenv("TTS_VOICE", _default_voice).strip() or _default_voice
TTS_NO_FALLBACK = os.getenv("TTS_NO_FALLBACK", "").strip().lower() in ("1", "true", "yes")


def _clean_text(text: str) -> str:
    return " ".join(str(text or "").replace("\r", " ").replace("\n", " ").split()).strip()


def _probe_duration(path: Path) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return 0.0
    try:
        result = subprocess.run(
            [
                ffprobe, "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        value = result.stdout.strip()
        return max(0.0, float(value)) if value else 0.0
    except (ValueError, OSError):
        return 0.0


def _estimate_duration(text: str) -> float:
    words = max(1, len(_clean_text(text).split()))
    return max(1.5, words / 2.35)


def _edge_voice_name() -> str:
    # Guard against a stale/placeholder secret like "en-IN" (a language tag,
    # not an Edge voice name) silently breaking synthesis.
    voice = TTS_VOICE
    if "Neural" not in voice:
        return "en-IN-NeerjaNeural"
    return voice


def _edge_synth(text: str, audio_path: Path, attempts: int = 3) -> float:
    if edge_tts is None:
        raise RuntimeError("edge-tts is not installed")

    voice = _edge_voice_name()
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            async def _run() -> None:
                communicate = edge_tts.Communicate(text, voice)
                await communicate.save(str(audio_path))

            asyncio.run(_run())
            if audio_path.exists() and audio_path.stat().st_size > 1000:
                return _probe_duration(audio_path) or _estimate_duration(text)
            last_error = RuntimeError("edge-tts produced no usable audio")
        except Exception as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(1.5 * attempt)  # backoff: 1.5s, 3s

    raise RuntimeError(f"edge-tts failed after {attempts} attempts: {last_error}")


def _openrouter_synth(text: str, audio_path: Path, attempts: int = 2) -> float:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set")

    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            r = requests.post(
                OPENROUTER_TTS_ENDPOINT,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://examcracker-ai.onrender.com",
                    "X-Title": "ExamCracker YouTube Automation",
                },
                json={
                    "model": OPENROUTER_TTS_MODEL,
                    "input": text,
                    "voice": TTS_VOICE,
                    "response_format": "mp3",
                },
                timeout=90,
            )
            if not r.ok:
                # Error responses are JSON, not audio.
                raise RuntimeError(f"OpenRouter TTS HTTP {r.status_code}: {r.text[:500]}")
            content_type = r.headers.get("Content-Type", "")
            if "audio" not in content_type:
                raise RuntimeError(f"OpenRouter TTS returned non-audio content-type {content_type!r}: {r.text[:300]}")
            audio_path.write_bytes(r.content)
            if audio_path.exists() and audio_path.stat().st_size > 1000:
                return _probe_duration(audio_path) or _estimate_duration(text)
            last_error = RuntimeError("OpenRouter TTS produced no usable audio")
        except Exception as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(2.0)

    raise RuntimeError(f"OpenRouter TTS ({OPENROUTER_TTS_MODEL}) failed after {attempts} attempts: {last_error}")


def _gtts_synth(text: str, audio_path: Path) -> float:
    if gTTS is None:
        raise RuntimeError("gTTS is not installed")

    # lang=en + tld=co.in gives Google's India English endpoint without
    # requiring Google Cloud billing or credentials.
    tts = gTTS(
        text=text,
        lang="en",
        tld="co.in",
        slow=False,
    )
    tts.save(str(audio_path))

    if not audio_path.exists() or audio_path.stat().st_size < 1000:
        raise RuntimeError("gTTS produced no usable audio")

    return _probe_duration(audio_path) or _estimate_duration(text)


def _espeak_synth(text: str, audio_path: Path) -> float:
    executable = shutil.which("espeak-ng") or shutil.which("espeak")
    if not executable:
        raise RuntimeError("espeak-ng/espeak is not installed")

    # Prefer Indian English if the runner has it; espeak will reject it on
    # installations without the voice, so retry with en.
    last_error = None
    for voice in ("en-in", "en"):
        try:
            result = subprocess.run(
                [executable, "-v", voice, "-s", "165", "-w", str(audio_path), text],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0 and audio_path.exists() and audio_path.stat().st_size > 1000:
                return _probe_duration(audio_path) or _estimate_duration(text)
            last_error = result.stderr.strip() or f"exit {result.returncode}"
        except Exception as exc:
            last_error = str(exc)

    raise RuntimeError(f"eSpeak Indian-English fallback failed: {last_error}")


def synthesize_scene(
    subtitle_text: str | None = None,
    tts_text: str | None = None,
    voice: str | None = None,
    audio_path: str | Path | None = None,
    ass_path: str | Path | None = None,
    overlay_text: str | None = None,
    *args,
    **kwargs,
):
    """Create narration audio.

    The old subtitle arguments are accepted for backward compatibility, but
    deliberately ignored. The function returns (audio_path, None, duration)
    so older callers do not break while render.py guarantees that no ASS
    subtitle filter is used.
    """
    # Support the old positional call:
    # synthesize_scene(scene_index, narration, tts_text, voice, on_screen_text)
    if isinstance(subtitle_text, int):
        positional = [subtitle_text, tts_text, voice, audio_path, ass_path, overlay_text, *args]
        narration = positional[1] if len(positional) > 1 else ""
        spoken = positional[2] if len(positional) > 2 else narration
        tts_text = spoken
        subtitle_text = narration

    spoken = _clean_text(tts_text or subtitle_text or "")
    if not spoken:
        raise ValueError("Cannot synthesize empty text")

    if audio_path is None:
        raise ValueError("audio_path is required")

    audio_path = Path(audio_path)
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        audio_path.unlink()
    except FileNotFoundError:
        pass

    errors: list[str] = []

    # Provider order now actually follows the TTS_PROVIDER secret instead of
    # always forcing gTTS. "edge" and "openrouter" sound like real human
    # voices; gTTS is flat/robotic but never blocked; espeak is the last resort.
    if TTS_PROVIDER == "edge":
        try:
            print(f"[tts] provider=edge voice={_edge_voice_name()}")
            duration = _edge_synth(spoken, audio_path)
            return audio_path, None, duration
        except Exception as exc:
            errors.append(f"edge: {exc}")
            print(f"[tts] edge-tts failed: {exc}")

    if TTS_PROVIDER == "openrouter":
        try:
            print(f"[tts] provider=openrouter model={OPENROUTER_TTS_MODEL} voice={TTS_VOICE}")
            duration = _openrouter_synth(spoken, audio_path)
            return audio_path, None, duration
        except Exception as exc:
            errors.append(f"openrouter: {exc}")
            print(f"[tts] OpenRouter TTS failed: {exc}")

    try:
        print("[tts] provider=gtts voice=Google India English (en/co.in)")
        duration = _gtts_synth(spoken, audio_path)
        return audio_path, None, duration
    except Exception as exc:
        errors.append(f"gtts: {exc}")
        print(f"[tts] gTTS failed: {exc}")

    try:
        print("[tts] provider=espeak voice=en-in")
        duration = _espeak_synth(spoken, audio_path)
        return audio_path, None, duration
    except Exception as exc:
        errors.append(f"espeak: {exc}")
        print(f"[tts] eSpeak failed: {exc}")

    raise RuntimeError("All Indian-English TTS providers failed: " + " | ".join(errors))
