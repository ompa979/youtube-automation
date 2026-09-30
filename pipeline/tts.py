"""Indian-English TTS using Microsoft Edge TTS (primary, free, no billing) with fallbacks.

Provider order:
1. edge          — en-IN-NeerjaExpressiveNeural. Excellent quality, no key,
                   no billing. Returns real per-word WordBoundary events.
                   Occasionally returns 403 on GitHub runners — retried 3×.
2. google_cloud  — Chirp3-HD (requires GOOGLE_CLOUD_TTS_KEY + billing enabled).
                   Only used if TTS_PROVIDER=google_cloud is explicitly set.
3. gtts          — Google India English endpoint. Flat/robotic but never blocked.
4. espeak-ng     — Offline last resort.

Set TTS_PROVIDER=edge      to use Edge neural voice (default — no cost, no key).
Set TTS_PROVIDER=google_cloud to force Chirp3-HD (requires billing on GCP).
Set TTS_PROVIDER=gtts      to force flat Google TTS.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import threading
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

try:
    from faster_whisper import WhisperModel as _WhisperModel
except ImportError:
    _WhisperModel = None

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

# Edge TTS voice (no key needed, highest clarity Indian English male educator voice)
EDGE_VOICE = os.getenv("TTS_VOICE", "en-IN-PrabhatNeural").strip() or "en-IN-PrabhatNeural"
EDGE_TTS_RATE = os.getenv("TTS_RATE", "-4%").strip() or "-4%"

# Caps how many scenes may hit the Edge-TTS websocket endpoint at the same
# instant. generate.py now processes scenes concurrently (ThreadPoolExecutor),
# which turned out to be the actual cause of the near-universal 403s seen in
# production logs: Microsoft's endpoint treats a burst of simultaneous
# connections from one source as bot-like and starts rejecting the handshake,
# even though each individual request is completely normal. One scene at a
# time on this specific call keeps the parallelism everywhere else in the
# pipeline (image fetch, other scenes' non-TTS work) while not looking like a
# flood to Microsoft. Tune via EDGE_TTS_CONCURRENCY if needed.
_EDGE_TTS_SEMAPHORE = threading.Semaphore(max(1, int(os.getenv("EDGE_TTS_CONCURRENCY", "1"))))


def _clean_text(text: str) -> str:
    return " ".join(str(text or "").replace("\r", " ").replace("\n", " ").split()).strip()


import re

def normalize_for_speech(text: str) -> str:
    """Preprocesses text for clear, natural Indian-accented educational TTS.

    Expands technical acronyms, exam names, symbols, and adds punctuation
    pauses so the neural voice does not stumble, slur, or rush through words.
    """
    s = text or ""
    # Strip emojis or special unicode
    s = re.sub(r"[\U00010000-\U0010ffff]", "", s)

    # Numbering and symbols
    s = re.sub(r"#(\d+)\b", r"number \1", s)
    s = re.sub(r"(\d+)\s*%", r"\1 percent", s)
    s = re.sub(r"\b(\d+)\s*x\b", r"\1 times", s, flags=re.I)
    s = re.sub(r"\s*&\s*", " and ", s)
    s = re.sub(r"\bvs\.?\b", "versus", s, flags=re.I)
    s = re.sub(r"\be\.?g\.?,?\s*", "for example, ", s, flags=re.I)
    s = re.sub(r"\bi\.?e\.?,?\s*", "that is, ", s, flags=re.I)
    s = re.sub(r"\bw\.?r\.?t\.?\b", "with respect to", s, flags=re.I)
    s = re.sub(r"\betc\.?\b", "and so on", s, flags=re.I)

    # Exam names & normal forms (phonetic spacing for crisp articulation)
    s = re.sub(r"\b1NF\b", "1 N F", s, flags=re.I)
    s = re.sub(r"\b2NF\b", "2 N F", s, flags=re.I)
    s = re.sub(r"\b3NF\b", "3 N F", s, flags=re.I)
    s = re.sub(r"\bBCNF\b", "B C N F", s, flags=re.I)

    s = re.sub(r"\bIBPS\s+SO\s+IT\b", "I B P S, S O, I T", s, flags=re.I)
    s = re.sub(r"\bIBPS\s+SO\b", "I B P S, S O", s, flags=re.I)
    s = re.sub(r"\bIBPS\s+PO\b", "I B P S, P O", s, flags=re.I)
    s = re.sub(r"\bIBPS\b", "I B P S", s)
    s = re.sub(r"\bSBI\s+PO\b", "S B I, P O", s, flags=re.I)
    s = re.sub(r"\bSBI\b", "S B I", s)
    s = re.sub(r"\bRBI\s+Grade\s+B\b", "R B I Grade B", s, flags=re.I)
    s = re.sub(r"\bRBI\b", "R B I", s)
    s = re.sub(r"\bUPSC\b", "U P S C", s)
    s = re.sub(r"\bSSC\s+CGL\b", "S S C, C G L", s, flags=re.I)
    s = re.sub(r"\bSSC\b", "S S C", s)

    # Technical acronyms
    s = re.sub(r"\bDBMS\b", "D B M S", s)
    s = re.sub(r"\bRDBMS\b", "R D B M S", s)
    s = re.sub(r"\bSQL\b", "S Q L", s)
    s = re.sub(r"\bACID\b", "A C I D", s)
    s = re.sub(r"\bTCP/IP\b", "T C P, I P", s, flags=re.I)
    s = re.sub(r"\bOSI\b", "O S I", s)
    s = re.sub(r"\bCPU\b", "C P U", s)
    s = re.sub(r"\bRAM\b", "R A M", s)
    s = re.sub(r"\bROM\b", "R O M", s)
    s = re.sub(r"\bAPI\b", "A P I", s)

    # Punctuation & pauses: dashes and slashes become natural commas/pauses
    s = re.sub(r"\s*[—–-]{2,}\s*", ", ", s)
    s = re.sub(r"\s*—\s*", ", ", s)
    s = re.sub(r"\s*/\s*", " or ", s)
    s = re.sub(r"\s*\(\s*", ", ", s)
    s = re.sub(r"\s*\)\s*", ", ", s)
    s = re.sub(r",+", ",", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def align_timings_to_script(word_timings: list[dict], script_text: str, duration: float) -> list[dict]:
    """Maps audio word timings back to the original script words for clean on-screen captions."""
    script_words = [w for w in (script_text or "").replace("\r", " ").replace("\n", " ").split() if w.strip()]
    if not script_words:
        return []
    if not word_timings:
        weights = [max(1.0, float(len(w)) + (2.0 if w.endswith((",", ";", ":")) else 4.0 if w.endswith((".", "!", "?")) else 0.0)) for w in script_words]
        total = sum(weights)
        t = 0.0
        res = []
        for w, wt in zip(script_words, weights):
            seg = duration * (wt / total)
            res.append({"word": w, "start": t, "end": t + seg})
            t += seg
        return res

    if len(word_timings) == len(script_words):
        return [{"word": sw, "start": wt["start"], "end": wt["end"]} for sw, wt in zip(script_words, word_timings)]

    weights = [max(1.0, float(len(w)) + (2.0 if w.endswith((",", ";", ":")) else 4.0 if w.endswith((".", "!", "?")) else 0.0)) for w in script_words]
    total = sum(weights)
    t_start = word_timings[0].get("start", 0.0)
    t_end = max(duration, word_timings[-1].get("end", duration))
    span = max(0.1, t_end - t_start)
    t = t_start
    res = []
    for w, wt in zip(script_words, weights):
        seg = span * (wt / total)
        res.append({"word": w, "start": t, "end": min(duration, t + seg)})
        t += seg
    return res


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
    return max(1.5, words / 2.1)


def _master_voice_file(path: Path) -> Path:
    """Phone-first narration mastering: compression, -14 LUFS normalization and limiter."""
    mastered = path.with_name(path.stem + "_mastered.mp3")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return path
    try:
        target=float(os.getenv("VOICE_LUFS","-14")); ceiling=float(os.getenv("VOICE_TRUE_PEAK","-1.5"))
        af=(f"highpass=f=75,acompressor=threshold=0.10:ratio=3.2:attack=8:release=120:makeup=2.5,loudnorm=I={target}:TP={ceiling}:LRA=7,alimiter=limit=0.89:attack=5:release=50")
        subprocess.run([ffmpeg,"-y","-i",str(path),"-af",af,"-c:a","libmp3lame","-b:a","192k",str(mastered)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True)
        if mastered.exists() and mastered.stat().st_size>2000: mastered.replace(path)
    except Exception as exc:
        print(f"[tts] voice mastering failed (non-fatal): {exc}")
    return path


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
# faster-whisper alignment — used after Chirp TTS to get real word timings
# ---------------------------------------------------------------------------

# Cache the model across scenes in the same process run (load once, use many).
_WHISPER_MODEL: "_WhisperModel | None" = None
_WHISPER_MODEL_SIZE = "tiny"  # tiny = ~40 MB, fast enough on a runner


def _load_whisper() -> "_WhisperModel | None":
    global _WHISPER_MODEL
    if _WhisperModel is None:
        return None
    if _WHISPER_MODEL is None:
        try:
            _WHISPER_MODEL = _WhisperModel(_WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
            print(f"[whisper] model loaded: {_WHISPER_MODEL_SIZE}")
        except Exception as exc:
            print(f"[whisper] WARNING: could not load model: {exc}")
            return None
    return _WHISPER_MODEL


def _whisper_align(audio_path: "Path", script_text: str) -> list[dict]:
    """Run faster-whisper on *audio_path* and return per-word timings.

    The transcript produced by whisper is aligned back to *script_text* so
    that specialist terms like '3NF', 'IBPS SO', 'TCP/IP' that whisper might
    mishear in the audio still appear correctly in the captions.  The
    alignment is a simple greedy token-match: we split both the whisper
    output and the script into words, match them positionally, and keep
    the whisper timestamps with the corrected script word.

    Returns [] on any failure so the caller silently falls back to the
    character-weight estimator.
    """
    model = _load_whisper()
    if model is None:
        return []
    try:
        segments, _info = model.transcribe(
            str(audio_path),
            word_timestamps=True,
            language="en",
            vad_filter=True,
        )
        # Flatten all word objects from all segments.
        heard_words: list[dict] = []
        for seg in segments:
            for w in (seg.words or []):
                heard_words.append({
                    "word": w.word.strip(),
                    "start": w.start,
                    "end": w.end,
                })
        if not heard_words:
            return []

        # Align whisper timings to the known script text so specialist terms
        # are never misheard.  Simple positional alignment: if both sequences
        # have the same length the match is 1-to-1.  If lengths differ we use
        # the whisper timestamps for as many script words as possible.
        script_words = _clean_text(script_text).split()
        aligned: list[dict] = []
        for i, sw in enumerate(script_words):
            if i < len(heard_words):
                hw = heard_words[i]
                aligned.append({"word": sw, "start": hw["start"], "end": hw["end"]})
            else:
                # Ran out of whisper words — estimate the tail proportionally.
                if aligned:
                    prev_end = aligned[-1]["end"]
                    remaining = len(script_words) - i
                    tail_duration = max(0.3, 0.4 * remaining)  # rough 400ms/word
                    step = tail_duration / remaining
                    for j, sw2 in enumerate(script_words[i:]):
                        s = prev_end + j * step
                        aligned.append({"word": sw2, "start": s, "end": s + step})
                break
        print(f"[whisper] aligned {len(aligned)}/{len(script_words)} script words")
        return aligned
    except Exception as exc:
        print(f"[whisper] WARNING: alignment failed (using estimator): {exc}")
        return []


# ---------------------------------------------------------------------------
# Provider: Microsoft Edge TTS (no key needed)
# ---------------------------------------------------------------------------

def _edge_voice_name() -> str:
    voice = os.getenv("TTS_VOICE", EDGE_VOICE).strip() or "en-IN-PrabhatNeural"
    if "Neural" not in voice:
        return "en-IN-PrabhatNeural"
    return voice


_EDGE_TICKS_PER_SECOND = 10_000_000  # edge-tts reports offset/duration in 100ns ticks


def _edge_synth(text: str, audio_path: Path, attempts: int = 3) -> tuple[float, list[dict]]:
    """Returns (duration_seconds, word_timings). word_timings comes straight
    from edge-tts's own WordBoundary events, so this is real per-word timing."""
    if edge_tts is None:
        raise RuntimeError("edge-tts is not installed")

    voice = _edge_voice_name()
    rate = os.getenv("TTS_RATE", EDGE_TTS_RATE).strip() or "-10%"
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        word_timings: list[dict] = []
        try:
            async def _run() -> None:
                communicate = edge_tts.Communicate(text, voice, rate=rate)
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

            with _EDGE_TTS_SEMAPHORE:
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
    """Create narration audio using high-quality Indian educator voices."""
    # Support old positional call: synthesize_scene(scene_index, narration, tts_text, ...)
    if isinstance(subtitle_text, int):
        positional = [subtitle_text, tts_text, voice, audio_path, ass_path, overlay_text, *args]
        narration = positional[1] if len(positional) > 1 else ""
        spoken = positional[2] if len(positional) > 2 else narration
        tts_text = spoken
        subtitle_text = narration

    raw_spoken = _clean_text(tts_text or subtitle_text or "")
    if not raw_spoken:
        raise ValueError("Cannot synthesize empty text")
    if audio_path is None:
        raise ValueError("audio_path is required")

    # Phonetic preprocessor expands acronyms, exam names, symbols, and adds breath pauses
    spoken = normalize_for_speech(raw_spoken)

    audio_path = Path(audio_path)
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        audio_path.unlink()
    except FileNotFoundError:
        pass

    errors: list[str] = []

    # 1. Google Cloud TTS Chirp3-HD — only if explicitly opted in AND key is set.
    if TTS_PROVIDER == "google_cloud" and GOOGLE_CLOUD_TTS_KEY:
        try:
            print(f"[tts] provider=google_cloud voice={GOOGLE_CLOUD_TTS_VOICE}")
            duration = _google_cloud_synth(spoken, audio_path)
            word_timings = _whisper_align(audio_path, raw_spoken)
            if not word_timings:
                word_timings = align_timings_to_script([], raw_spoken, duration)
            audio_path=_master_voice_file(audio_path); duration=_probe_duration(audio_path) or duration
            return audio_path, word_timings, duration
        except Exception as exc:
            errors.append(f"google_cloud: {exc}")
            print(f"[tts] Google Cloud TTS failed: {exc}")

    # 2. Microsoft Edge TTS — PrabhatNeural / NeerjaNeural Indian English (no key needed).
    if TTS_PROVIDER != "gtts":
        try:
            active_voice = _edge_voice_name()
            active_rate = os.getenv("TTS_RATE", EDGE_TTS_RATE).strip() or "-10%"
            print(f"[tts] provider=edge voice={active_voice} rate={active_rate}")
            duration, word_timings = _edge_synth(spoken, audio_path)
            # Align timings to the original display script text for on-screen captions
            aligned_timings = align_timings_to_script(word_timings, raw_spoken, duration)
            audio_path=_master_voice_file(audio_path); duration=_probe_duration(audio_path) or duration
            return audio_path, aligned_timings, duration
        except Exception as exc:
            errors.append(f"edge: {exc}")
            print(f"[tts] Edge-TTS failed: {exc}")

    # 3. gTTS Google India endpoint (flat but never blocked)
    try:
        print("[tts] provider=gtts voice=Google India English")
        duration = _gtts_synth(spoken, audio_path)
        aligned = align_timings_to_script([], raw_spoken, duration)
        audio_path=_master_voice_file(audio_path); duration=_probe_duration(audio_path) or duration
        return audio_path, aligned, duration
    except Exception as exc:
        errors.append(f"gtts: {exc}")
        print(f"[tts] gTTS failed: {exc}")

    # 4. eSpeak offline last resort
    try:
        print("[tts] provider=espeak voice=en-in")
        duration = _espeak_synth(spoken, audio_path)
        audio_path=_master_voice_file(audio_path); duration=_probe_duration(audio_path) or duration
        return audio_path, _estimate_word_timings(spoken, duration), duration
    except Exception as exc:
        errors.append(f"espeak: {exc}")
        print(f"[tts] eSpeak failed: {exc}")

    raise RuntimeError("All TTS providers failed: " + " | ".join(errors))
