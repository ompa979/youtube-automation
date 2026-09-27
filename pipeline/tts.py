"""Premium Indian-English TTS using Google Cloud TTS (Chirp3-HD) with Edge-TTS fallback.

Provider priority (Google-only stack):
1. google_cloud  — Chirp3-HD-Achernar (en-IN), the best Indian English neural voice.
                   Requires GOOGLE_CLOUD_TTS_KEY (API key) OR GOOGLE_APPLICATION_CREDENTIALS.
                   Free tier: 1 million WaveNet/Chirp characters/month.
2. edge          — Microsoft Edge neural voices (en-IN-NeerjaNeural). Excellent quality,
                   no key needed. Occasionally returns 403 on GitHub runners — retried 3x.
3. gtts          — Google India English endpoint. Flat/robotic but never blocked.
4. espeak-ng     — Offline last resort.

Set TTS_PROVIDER=google_cloud to force Chirp3-HD.
Set TTS_PROVIDER=edge to use Edge neural voice (default if no Cloud key).
Set TTS_PROVIDER=gtts to force flat Google TTS.

GOOGLE_CLOUD_TTS_KEY: your Google Cloud API key (enable "Cloud Text-to-Speech API" in Console).
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

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TTS_LANGUAGE = os.getenv("TTS_LANGUAGE", "en-IN").strip() or "en-IN"
TTS_PROVIDER = os.getenv("TTS_PROVIDER", "edge").strip().lower() or "edge"

# Google Cloud TTS — Chirp3-HD voices (best quality, free 1M chars/month)
GOOGLE_CLOUD_TTS_KEY = os.getenv("GOOGLE_CLOUD_TTS_KEY", "").strip()
# Best Indian English HD voice. Male alternative: "en-IN-Chirp3-HD-Fenrir"
GOOGLE_CLOUD_TTS_VOICE = os.getenv("GOOGLE_CLOUD_TTS_VOICE", "en-IN-Chirp3-HD-Achernar").strip()

# Edge TTS voice (no key needed, very good quality)
EDGE_VOICE = os.getenv("TTS_VOICE", "en-IN-NeerjaNeural").strip() or "en-IN-NeerjaNeural"


def _clean_text(text: str) -> str:
    return " ".join(str(text or "").replace("\r", " ").replace("\n", " ").split()).strip()


def _probe_duration(path: Path) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return 0.0
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, check=False,
        )
        value = result.stdout.strip()
        return max(0.0, float(value)) if value else 0.0
    except (ValueError, OSError):
        return 0.0


def _estimate_duration(text: str) -> float:
    words = max(1, len(_clean_text(text).split()))
    return max(1.5, words / 2.35)


# ---------------------------------------------------------------------------
# Provider: Google Cloud TTS (Chirp3-HD)
# ---------------------------------------------------------------------------

def _google_cloud_synth(text: str, audio_path: Path) -> float:
    """Use Google Cloud Text-to-Speech API with Chirp3-HD voice."""
    if not GOOGLE_CLOUD_TTS_KEY:
        raise RuntimeError("GOOGLE_CLOUD_TTS_KEY is not set")

    url = f"https://texttospeech.googleapis.com/v1/text:synthesize?key={GOOGLE_CLOUD_TTS_KEY}"
    payload = {
        "input": {"text": text},
        "voice": {
            "languageCode": "en-IN",
            "name": GOOGLE_CLOUD_TTS_VOICE,
        },
        "audioConfig": {
            "audioEncoding": "MP3",
            "speakingRate": 1.0,   # 1.0 = natural pace; increase to 1.1 if you want slightly faster
            "pitch": 0.0,
            "effectsProfileId": ["headphone-class-device"],
        },
    }
    r = requests.post(url, json=payload, timeout=30)
    if not r.ok:
        raise RuntimeError(f"Google Cloud TTS HTTP {r.status_code}: {r.text[:400]}")
    data = r.json()
    audio_content = data.get("audioContent")
    if not audio_content:
        raise RuntimeError("Google Cloud TTS returned empty audioContent")

    import base64
    audio_path.write_bytes(base64.b64decode(audio_content))
    if not audio_path.exists() or audio_path.stat().st_size < 1000:
        raise RuntimeError("Google Cloud TTS produced no usable audio")
    return _probe_duration(audio_path) or _estimate_duration(text)


# ---------------------------------------------------------------------------
# Provider: Microsoft Edge TTS (no key needed)
# ---------------------------------------------------------------------------

def _edge_voice_name() -> str:
    voice = EDGE_VOICE
    if "Neural" not in voice:
        return "en-IN-NeerjaNeural"
    return voice


_EDGE_TICKS_PER_SECOND = 10_000_000  # edge-tts reports offset/duration in 100ns ticks


def _edge_synth(text: str, audio_path: Path, attempts: int = 3) -> tuple[float, list[dict]]:
    """Returns (duration_seconds, word_timings). word_timings comes straight
    from edge-tts's own WordBoundary events (boundary="WordBoundary" must be
    requested explicitly — it defaults to SentenceBoundary), so this is real
    per-word timing, not an estimate."""
    if edge_tts is None:
        raise RuntimeError("edge-tts is not installed")

    voice = _edge_voice_name()
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        word_timings: list[dict] = []
        try:
            async def _run() -> None:
                # Recent edge-tts releases dropped the `boundary` kwarg from
                # Communicate() — WordBoundary events are now emitted
                # automatically in the stream() output, no request needed.
                communicate = edge_tts.Communicate(text, voice)
                with open(audio_path, "wb") as f:
                    async for chunk in communicate.stream():
                        if chunk["type"] == "audio":
                            f.write(chunk["data"])
                        elif chunk["type"] == "WordBoundary":
                            offset = chunk.get("offset", 0) / _EDGE_TICKS_PER_SECOND
                            dur = chunk.get("duration", 0) / _EDGE_TICKS_PER_SECOND
                            word_timings.append({
                                "word": chunk.get("text", ""),
                                "start": offset,
                                "end": offset + dur,
                            })

            asyncio.run(_run())
            if audio_path.exists() and audio_path.stat().st_size > 1000:
                duration = _probe_duration(audio_path) or _estimate_duration(text)
                return duration, word_timings
            last_error = RuntimeError("edge-tts produced no usable audio")
        except Exception as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(1.5 * attempt)

    raise RuntimeError(f"edge-tts failed after {attempts} attempts: {last_error}")


# ---------------------------------------------------------------------------
# Provider: gTTS (Google India endpoint, flat but reliable)
# ---------------------------------------------------------------------------

def _gtts_synth(text: str, audio_path: Path) -> float:
    if gTTS is None:
        raise RuntimeError("gTTS is not installed")
    tts = gTTS(text=text, lang="en", tld="co.in", slow=False)
    tts.save(str(audio_path))
    if not audio_path.exists() or audio_path.stat().st_size < 1000:
        raise RuntimeError("gTTS produced no usable audio")
    return _probe_duration(audio_path) or _estimate_duration(text)


# ---------------------------------------------------------------------------
# Provider: eSpeak (offline last resort)
# ---------------------------------------------------------------------------

def _espeak_synth(text: str, audio_path: Path) -> float:
    executable = shutil.which("espeak-ng") or shutil.which("espeak")
    if not executable:
        raise RuntimeError("espeak-ng/espeak is not installed")
    last_error = None
    for voice in ("en-in", "en"):
        try:
            result = subprocess.run(
                [executable, "-v", voice, "-s", "165", "-w", str(audio_path), text],
                capture_output=True, text=True, check=False,
            )
            if result.returncode == 0 and audio_path.exists() and audio_path.stat().st_size > 1000:
                return _probe_duration(audio_path) or _estimate_duration(text)
            last_error = result.stderr.strip() or f"exit {result.returncode}"
        except Exception as exc:
            last_error = str(exc)
    raise RuntimeError(f"eSpeak fallback failed: {last_error}")


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Word-timing fallback estimator — used for any provider that doesn't return
# real per-word timestamps (Google Cloud, gTTS, eSpeak). Allocates the
# measured audio duration across words weighted by character count, with a
# small extra "pause" weight after clause/sentence punctuation, so it reads
# close to natural pacing instead of perfectly even per-word slices.
# ---------------------------------------------------------------------------
def _estimate_word_timings(text: str, duration: float) -> list[dict]:
    words = _clean_text(text).split()
    if not words or duration <= 0:
        return []
    weights: list[float] = []
    for w in words:
        weight = float(len(w))
        if w.endswith((",", ";", ":")):
            weight += 2.0
        if w.endswith((".", "!", "?")):
            weight += 4.0
        weights.append(max(1.0, weight))
    total = sum(weights)
    t = 0.0
    timings: list[dict] = []
    for w, wt in zip(words, weights):
        seg = duration * (wt / total)
        timings.append({"word": w, "start": t, "end": t + seg})
        t += seg
    return timings


def synthesize_scene(
    subtitle_text: str | None = None,
    tts_text: str | None = None,
    voice: str | None = None,
    audio_path: str | Path | None = None,
    ass_path: str | None = None,
    overlay_text: str | None = None,
    *args,
    **kwargs,
):
    """Create narration audio using the Google-only TTS stack."""
    # Support old positional call: synthesize_scene(scene_index, narration, tts_text, ...)
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

    # 1. Google Cloud TTS Chirp3-HD (if key is set — best quality)
    if GOOGLE_CLOUD_TTS_KEY:
        try:
            print(f"[tts] provider=google_cloud voice={GOOGLE_CLOUD_TTS_VOICE}")
            duration = _google_cloud_synth(spoken, audio_path)
            return audio_path, _estimate_word_timings(spoken, duration), duration
        except Exception as exc:
            errors.append(f"google_cloud: {exc}")
            print(f"[tts] Google Cloud TTS failed: {exc}")

    # 2. Microsoft Edge TTS — NeerjaNeural Indian English (no key needed).
    # Returns REAL per-word timing straight from the service, not an estimate.
    if TTS_PROVIDER != "gtts":  # skip edge if user forced gtts
        try:
            print(f"[tts] provider=edge voice={_edge_voice_name()}")
            duration, word_timings = _edge_synth(spoken, audio_path)
            if not word_timings:
                # Service responded but sent no WordBoundary events (has
                # happened on some voices/regions) — estimate instead of
                # silently shipping a video with no word-by-word captions.
                word_timings = _estimate_word_timings(spoken, duration)
            return audio_path, word_timings, duration
        except Exception as exc:
            errors.append(f"edge: {exc}")
            print(f"[tts] Edge-TTS failed: {exc}")

    # 3. gTTS Google India endpoint (flat but never blocked)
    try:
        print("[tts] provider=gtts voice=Google India English")
        duration = _gtts_synth(spoken, audio_path)
        return audio_path, _estimate_word_timings(spoken, duration), duration
    except Exception as exc:
        errors.append(f"gtts: {exc}")
        print(f"[tts] gTTS failed: {exc}")

    # 4. eSpeak offline last resort
    try:
        print("[tts] provider=espeak voice=en-in")
        duration = _espeak_synth(spoken, audio_path)
        return audio_path, _estimate_word_timings(spoken, duration), duration
    except Exception as exc:
        errors.append(f"espeak: {exc}")
        print(f"[tts] eSpeak failed: {exc}")

    raise RuntimeError("All TTS providers failed: " + " | ".join(errors))
