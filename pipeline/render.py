"""Premium 9:16 educational rendering with burned-in subtitles + thumbnail.

Layers per scene clip (bottom to top):
  1. Ken Burns motion on the AI image
  2. Narration subtitle strip  (bottom-anchored 170px safe margin, max 3
                                 lines, font shrinks to fit, style rotates
                                 bar/pill/card across scenes, fades in)
  3. Keyword caption            (y≈70%, ALL-CAPS, tinted with the niche's
                                 accent color, fixed clearance above the
                                 subtitle block, fades in)

Variety features (anti-monotone pass):
  #1  Accent color per topic category (niche)         -> _accent_for_category
  #2  Caption box style rotates bar / pill / card      -> _CAPTION_STYLES
  #3  Subtitle + keyword fade in instead of popping in -> alpha= expression
  #4  Crossfade transition type rotates per cut         -> _TRANSITIONS
  #5  Background music track picked per-video by hash   -> _pick_music
  #6  Short whoosh SFX layered under every scene cut     -> assets/sfx/
  #7  (script_gen.py) hook style rotates per topic
  #8  (script_gen.py) prompt now asks for varied pacing
  #9  Rotating outro CTA card appended as a final "scene" -> _make_outro_clip
  #10 Thumbnail: best-of-4 candidate frames, scored       -> extract_best_thumbnail
      for contrast/brightness, instead of a fixed 0.5s grab
"""
from __future__ import annotations

import hashlib
import subprocess
import textwrap
from pathlib import Path

from .config import WORK_DIR, OUT_DIR, ASSETS_DIR

W, H = 1080, 1920
FPS = 30


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"Command failed ({proc.returncode}):\n{' '.join(cmd)}\n\n"
            f"--- stderr tail ---\n{proc.stderr[-3500:]}"
        )


def _stable_hash(text: str) -> int:
    """Deterministic hash (unlike Python's randomized str hash) so the same
    topic/slug always rotates to the same style — reproducible renders,
    but different topics land on different styles/colors/tracks."""
    return int(hashlib.md5(text.encode("utf-8")).hexdigest(), 16)


# ---------------------------------------------------------------------------
# #1 Accent color per niche/category
# ---------------------------------------------------------------------------
ACCENT_PALETTE: dict[str, str] = {
    "exam_concepts": "0x1B3A6B",       # deep blue
    "science_explainers": "0x1F6B3A",  # deep green
    "default": "0x2B2B2E",             # neutral dark gray (original look)
}
_FALLBACK_ACCENTS = ["0x1B3A6B", "0x1F6B3A", "0x6B3A1F", "0x5A1F6B", "0x6B1F3A", "0x1F5A6B"]


def _accent_for_category(category: str) -> str:
    if category in ACCENT_PALETTE:
        return ACCENT_PALETTE[category]
    if not category:
        return ACCENT_PALETTE["default"]
    return _FALLBACK_ACCENTS[_stable_hash(category) % len(_FALLBACK_ACCENTS)]


# ---------------------------------------------------------------------------
# #2 Caption box style rotation
# ---------------------------------------------------------------------------
_CAPTION_STYLES = ("bar", "pill", "card")


def _escape_drawtext(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\u2019")
        .replace("%", "\\%")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace("<", "\\<")
        .replace(">", "\\>")
        .replace("{", "\\{")
        .replace("}", "\\}")
    )


def _motion_filter(direction: int, total_frames: int) -> str:
    mode = direction % 4
    if mode == 0:
        z = "1.00+0.14*on/{n}".format(n=max(total_frames, 1))
        x = "iw/2-(iw/zoom/2)-45*on/{n}".format(n=max(total_frames, 1))
        y = "ih/2-(ih/zoom/2)"
    elif mode == 1:
        z = "1.14-0.10*on/{n}".format(n=max(total_frames, 1))
        x = "iw/2-(iw/zoom/2)+55*on/{n}".format(n=max(total_frames, 1))
        y = "ih/2-(ih/zoom/2)-35*on/{n}".format(n=max(total_frames, 1))
    elif mode == 2:
        z = "1.03+0.09*on/{n}".format(n=max(total_frames, 1))
        x = "iw/2-(iw/zoom/2)"
        y = "ih/2-(ih/zoom/2)+55*on/{n}".format(n=max(total_frames, 1))
    else:
        z = "1.12-0.08*on/{n}".format(n=max(total_frames, 1))
        x = "iw/2-(iw/zoom/2)-55*on/{n}".format(n=max(total_frames, 1))
        y = "ih/2-(ih/zoom/2)+30*on/{n}".format(n=max(total_frames, 1))
    return (
        f"scale={W*2}:{H*2}:force_original_aspect_ratio=increase,"
        f"crop={W*2}:{H*2},"
        f"zoompan=z='{z}':x='{x}':y='{y}':d={total_frames}:s={W}x{H}:fps={FPS},"
        "eq=contrast=1.045:saturation=1.035:brightness=0.004,"
        "unsharp=5:5:0.35:5:5:0,format=yuv420p"
    )


def _dynamic_fontsize(narration: str) -> int:
    """Starting font size guess for a narration length. _fit_subtitle() will
    shrink further if the wrapped text still doesn't fit in 3 lines."""
    char_count = len(narration)
    if char_count < 60:
        return 48
    if char_count < 100:
        return 42
    if char_count < 140:
        return 36
    return 30


def _max_chars_for_fontsize(fontsize: int) -> int:
    """Character width that keeps a wrapped line at roughly the same pixel
    width (~900px, safely inside the 1080px canvas) regardless of font size,
    so smaller tiers don't randomly produce wider or narrower lines."""
    return max(18, int(900 / (fontsize * 0.55)))


def _fit_subtitle(narration: str) -> tuple[int, str]:
    """Pick a font size + line-wrap that (a) matches the length tier and
    (b) is HARD CAPPED at 3 lines, shrinking further if needed. This is what
    keeps a long sentence from growing tall enough to run off the bottom of
    the frame."""
    text = narration.strip()
    fontsize = _dynamic_fontsize(text)
    while fontsize >= 24:
        max_chars = _max_chars_for_fontsize(fontsize)
        lines = textwrap.wrap(text, width=max_chars, break_long_words=False)
        if len(lines) <= 3:
            return fontsize, "\n".join(lines)
        fontsize -= 4
    # Extreme fallback (shouldn't normally trigger): smallest size, hard-cut to 3 lines.
    max_chars = _max_chars_for_fontsize(24)
    lines = textwrap.wrap(text, width=max_chars, break_long_words=False)[:3]
    return 24, "\n".join(lines)


# #3 shared fade-in: text ramps from invisible to fully opaque over 0.35s at
# the start of each scene clip, instead of popping in fully-formed.
_FADE_IN_ALPHA = "alpha='min(1\\,t/0.35)'"


def _keyword_filter(text: str, accent: str) -> str:
    """Keyword/memory-cue caption at y≈70% — short ALL-CAPS label, tinted
    with the video's accent color so it reads as branded rather than a
    generic gray box on every single video."""
    safe = _escape_drawtext(text.strip().upper())
    if not safe:
        return ""
    return (
        f"drawtext=font='Inter':text='{safe}':fontcolor=white:fontsize=58:"
        f"borderw=6:bordercolor=black@0.85:box=1:boxcolor={accent}@0.45:boxborderw=24:"
        f"x=(w-text_w)/2:y=h*0.70:line_spacing=8:{_FADE_IN_ALPHA}"
    )


def _subtitle_filter(narration: str, style: str, accent: str) -> str:
    """Burned-in subtitle strip, BOTTOM-anchored with a 170px safe margin.

    y=h-text_h-170 uses ffmpeg's own rendered-height variable, so as the
    text gets taller the block grows UPWARD and the bottom edge always
    stays a fixed 170px above the frame edge (clear of YouTube Shorts' own
    UI — progress bar / caption toggle) — regardless of caption style.

    style rotates per scene index (see _CAPTION_STYLES):
      "bar"  - classic centered neutral-dark box (the original look)
      "pill" - centered, accent-colored, extra horizontal padding
      "card" - left-aligned, accent-colored, compact padding
    """
    if not narration or not narration.strip():
        return ""
    fontsize, wrapped = _fit_subtitle(narration)
    safe = _escape_drawtext(wrapped)
    if not safe:
        return ""

    if style == "pill":
        box_color = f"{accent}@0.62"
        box_border = "14|46|14|46"  # top|right|bottom|left — wide pill padding
        x_expr = "(w-text_w)/2"
    elif style == "card":
        box_color = f"{accent}@0.70"
        box_border = "16"
        x_expr = "70"
    else:  # "bar" — original neutral look
        box_color = "black@0.55"
        box_border = "20"
        x_expr = "(w-text_w)/2"

    return (
        f"drawtext=font='Inter':text='{safe}':fontcolor=white:fontsize={fontsize}:"
        "borderw=4:bordercolor=black@0.9:"
        f"box=1:boxcolor={box_color}:boxborderw={box_border}:"
        f"x={x_expr}:y=h-text_h-170:"
        f"line_spacing=10:{_FADE_IN_ALPHA}"
    )


def _ken_burns_clip(
    image: Path,
    duration: float,
    out: Path,
    direction: int = 1,
    on_screen_text: str = "",
    narration: str = "",
    caption_style: str = "bar",
    accent: str = ACCENT_PALETTE["default"],
) -> None:
    total_frames = max(int(duration * FPS), 1)
    vf = _motion_filter(direction, total_frames)

    keyword_f = _keyword_filter(on_screen_text, accent) if on_screen_text else ""
    subtitle_f = _subtitle_filter(narration, caption_style, accent) if narration else ""

    if keyword_f:
        vf = f"{vf},{keyword_f}"
    if subtitle_f:
        vf = f"{vf},{subtitle_f}"

    _run([
        "ffmpeg", "-y", "-loop", "1", "-i", str(image),
        "-vf", vf, "-t", f"{duration:.3f}", "-r", str(FPS),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "17",
        "-profile:v", "high", "-level", "4.2", "-pix_fmt", "yuv420p", str(out),
    ])


# ---------------------------------------------------------------------------
# #9 Rotating outro CTA card — appended as a final "scene" before joining
# ---------------------------------------------------------------------------
CTA_PHRASES = [
    "Follow for more",
    "Which fact surprised you? Comment below",
    "Part 2 tomorrow — stay tuned",
    "Save this for revision",
    "Share this with a friend preparing for exams",
]


def _pick_cta(seed: str) -> str:
    return CTA_PHRASES[_stable_hash(seed) % len(CTA_PHRASES)]


def _make_outro_clip(accent: str, cta_text: str, out: Path, duration: float = 1.3) -> None:
    safe = _escape_drawtext(cta_text.strip())
    vf = (
        f"drawtext=font='Inter':text='{safe}':fontcolor=white:fontsize=54:"
        "borderw=4:bordercolor=black@0.85:"
        "x=(w-text_w)/2:y=(h-text_h)/2:line_spacing=10,"
        "fade=t=in:d=0.15:alpha=1"
    )
    _run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c={accent}:s={W}x{H}:d={duration:.3f}",
        "-vf", vf, "-r", str(FPS),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "17",
        "-profile:v", "high", "-level", "4.2", "-pix_fmt", "yuv420p", str(out),
    ])


# ---------------------------------------------------------------------------
# #10 Best-of-N thumbnail scoring
# ---------------------------------------------------------------------------
def extract_thumbnail(video_path: Path, out: Path, at_sec: float = 0.5) -> Path:
    """Extract a single frame from the video as a JPEG thumbnail (fixed timestamp,
    used as a fallback if best-of-N scoring can't find any usable candidate)."""
    _run([
        "ffmpeg", "-y", "-i", str(video_path),
        "-ss", f"{at_sec:.2f}", "-vframes", "1",
        "-q:v", "2",   # JPEG quality 2 = very high
        str(out),
    ])
    if not out.exists() or out.stat().st_size < 5000:
        raise RuntimeError(f"Thumbnail extraction failed: {out}")
    print(f"[render] thumbnail={out} size={out.stat().st_size // 1024}KB")
    return out


def _score_frame(path: Path) -> float:
    """Higher = more 'thumbnail-worthy': rewards contrast (a visually punchy,
    instantly-readable frame), penalizes frames that are too dark or too
    bright (washed out / crushed-black candidates)."""
    from PIL import Image
    img = Image.open(path).convert("L").resize((160, 284))
    pixels = list(img.getdata())
    n = len(pixels)
    mean = sum(pixels) / n
    variance = sum((p - mean) ** 2 for p in pixels) / n
    contrast = variance ** 0.5
    brightness_penalty = abs(mean - 128) / 128  # 0 = ideal midtone, 1 = worst
    return contrast * (1 - 0.3 * brightness_penalty)


def extract_best_thumbnail(video_path: Path, out: Path, scene0_duration: float) -> Path:
    """Sample several candidate frames from within scene 0 and keep whichever
    scores best for contrast/brightness, instead of always grabbing whatever
    happened to be on screen at a fixed 0.5s."""
    hi = max(0.2, min(scene0_duration - 0.15, 1.8))
    if hi <= 0.25:
        candidate_times = [0.15]
    else:
        n = 4
        candidate_times = [0.15 + i * (hi - 0.15) / (n - 1) for i in range(n)]

    best_path: Path | None = None
    best_score = -1.0
    tmp_paths: list[Path] = []

    for i, t in enumerate(candidate_times):
        tmp = out.parent / f"_thumb_candidate_{i}.jpg"
        try:
            _run([
                "ffmpeg", "-y", "-i", str(video_path),
                "-ss", f"{t:.2f}", "-vframes", "1", "-q:v", "2", str(tmp),
            ])
        except Exception as exc:
            print(f"[!] thumbnail candidate t={t:.2f}s failed (non-fatal): {exc}")
            continue
        if not tmp.exists() or tmp.stat().st_size < 5000:
            continue
        tmp_paths.append(tmp)
        try:
            score = _score_frame(tmp)
        except Exception as exc:
            print(f"[!] thumbnail scoring failed for t={t:.2f}s (non-fatal): {exc}")
            score = 0.0
        print(f"[render] thumbnail candidate t={t:.2f}s score={score:.1f}")
        if score > best_score:
            best_score = score
            best_path = tmp

    if best_path is None:
        print("[!] no usable thumbnail candidate — falling back to fixed 0.5s grab")
        return extract_thumbnail(video_path, out, at_sec=0.5)

    best_path.replace(out)
    for tmp in tmp_paths:
        if tmp.exists() and tmp != out:
            tmp.unlink(missing_ok=True)
    print(f"[render] thumbnail chosen: score={best_score:.1f} size={out.stat().st_size // 1024}KB")
    return out


# ---------------------------------------------------------------------------
# #4 Crossfade transition variety
# ---------------------------------------------------------------------------
_TRANSITIONS = ["fade", "wipeleft", "slideup", "circlecrop", "dissolve"]


def _join_with_transitions(clips: list[Path], durations: list[float], out: Path) -> list[float]:
    """Joins clips with a rotating crossfade transition type per cut.
    Returns the list of cut center-times (seconds, in the joined timeline) —
    used to time the whoosh SFX so it lands exactly on each visual cut."""
    if len(clips) == 1:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(clips[0]), "-c", "copy", str(out)],
            check=True, capture_output=True, text=True,
        )
        return []

    trans = 0.22
    inputs: list[str] = []
    for clip in clips:
        inputs += ["-i", str(clip)]

    filters = []
    cut_offsets: list[float] = []
    current = "[0:v]"
    offset = max(durations[0] - trans, 0.05)
    for i in range(1, len(clips)):
        nxt = f"[{i}:v]"
        out_label = f"[v{i}]"
        t_type = _TRANSITIONS[(i - 1) % len(_TRANSITIONS)]
        filters.append(f"{current}{nxt}xfade=transition={t_type}:duration={trans}:offset={offset:.3f}{out_label}")
        cut_offsets.append(offset + trans / 2)
        current = out_label
        offset += max(durations[i] - trans, 0.05)

    cmd = [
        "ffmpeg", "-y", *inputs,
        "-filter_complex", ";".join(filters),
        "-map", current,
        "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p", str(out),
    ]
    _run(cmd)
    return cut_offsets


def _concat_audio(paths: list[Path], out: Path) -> None:
    listfile = WORK_DIR / "audio_concat.txt"
    listfile.write_text("\n".join(f"file '{p.resolve()}'" for p in paths), encoding="utf-8")
    _run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
        "-c:a", "libmp3lame", "-b:a", "192k", str(out),
    ])


# ---------------------------------------------------------------------------
# #5 Music track rotation (by video, not always the alphabetically-first one)
# ---------------------------------------------------------------------------
def _pick_music(seed: str | None = None) -> Path | None:
    music_dir = ASSETS_DIR / "music"
    if not music_dir.exists():
        return None
    tracks = sorted(music_dir.glob("*.mp3")) + sorted(music_dir.glob("*.m4a"))
    if not tracks:
        return None
    if seed is None:
        return tracks[0]
    return tracks[_stable_hash(seed) % len(tracks)]


# ---------------------------------------------------------------------------
# #6 Whoosh SFX at every scene cut
# ---------------------------------------------------------------------------
def _pick_sfx() -> Path | None:
    sfx_dir = ASSETS_DIR / "sfx"
    if not sfx_dir.exists():
        return None
    tracks = sorted(sfx_dir.glob("*.mp3")) + sorted(sfx_dir.glob("*.wav"))
    return tracks[0] if tracks else None


def assemble_video(
    scene_images: list[Path],
    scene_audios: list[Path],
    scene_ass: list[Path] | None,
    scene_durations: list[float],
    slug: str,
    scene_texts: list[str] | None = None,
    scene_narrations: list[str] | None = None,
    category: str = "default",
) -> Path:
    del scene_ass
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if not scene_images or not scene_audios or len(scene_images) != len(scene_audios):
        raise ValueError("Cannot render video: scene image/audio counts do not match")

    accent = _accent_for_category(category)

    clips: list[Path] = []
    actual_durations: list[float] = []

    for i, (img, dur) in enumerate(zip(scene_images, scene_durations)):
        actual = max(float(dur), 1.0)
        clip = WORK_DIR / f"clip_{i:02d}.mp4"
        keyword = scene_texts[i] if scene_texts and i < len(scene_texts) else ""
        narration = scene_narrations[i] if scene_narrations and i < len(scene_narrations) else ""
        style = _CAPTION_STYLES[i % len(_CAPTION_STYLES)]
        _ken_burns_clip(
            img, actual, clip, direction=i, on_screen_text=keyword, narration=narration,
            caption_style=style, accent=accent,
        )
        clips.append(clip)
        actual_durations.append(actual)

    first_scene_duration = actual_durations[0] if actual_durations else 1.0

    # #9 Rotating outro CTA card, appended as a final "scene" so it also
    # gets a (rotated) crossfade transition into it.
    outro_clip = WORK_DIR / "clip_outro.mp4"
    cta_text = _pick_cta(slug)
    outro_duration = 1.3
    try:
        _make_outro_clip(accent, cta_text, outro_clip, duration=outro_duration)
        clips.append(outro_clip)
        actual_durations.append(outro_duration)
    except Exception as exc:
        print(f"[!] Outro card failed (non-fatal, skipping): {exc}")

    silent_video = WORK_DIR / "silent_video.mp4"
    cut_offsets = _join_with_transitions(clips, actual_durations, silent_video)

    voice = WORK_DIR / "voice.mp3"
    _concat_audio(scene_audios, voice)
    final = OUT_DIR / f"{slug}.mp4"
    music = _pick_music(seed=slug)
    sfx = _pick_sfx() if cut_offsets else None

    common_video = [
        "-c:v", "libx264", "-preset", "medium", "-crf", "17",
        "-profile:v", "high", "-level", "4.2", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
    ]

    # Build the audio graph: voice (always) + music (optional, ducked +
    # looped) + one delayed/ducked whoosh hit per scene cut (optional).
    audio_inputs = [voice]
    parts = ["[1:a]volume=1.0,aformat=channel_layouts=stereo[voice]"]
    mix_labels = ["[voice]"]
    next_idx = 2

    if music:
        audio_inputs.append(music)
        parts.append(
            f"[{next_idx}:a]volume=0.035,aloop=loop=-1:size=2e9,aformat=channel_layouts=stereo[music]"
        )
        mix_labels.append("[music]")
        next_idx += 1

    if sfx:
        audio_inputs.append(sfx)
        sfx_idx = next_idx
        next_idx += 1
        for i, off in enumerate(cut_offsets):
            ms = max(int(off * 1000), 0)
            label = f"[wh{i}]"
            parts.append(
                f"[{sfx_idx}:a]adelay={ms}|{ms},volume=0.22,aformat=channel_layouts=stereo{label}"
            )
            mix_labels.append(label)

    parts.append(f"{''.join(mix_labels)}amix=inputs={len(mix_labels)}:duration=first:dropout_transition=0[aout]")
    fc = ";".join(parts)

    cmd = [
        "ffmpeg", "-y", "-i", str(silent_video),
    ]
    for p in audio_inputs:
        cmd += ["-i", str(p)]
    cmd += [
        "-filter_complex", fc,
        "-map", "0:v", "-map", "[aout]",
        *common_video, "-c:a", "aac", "-b:a", "192k", "-shortest", str(final),
    ]

    try:
        _run(cmd)
    except Exception as exc:
        # Whoosh/music mixing is a nice-to-have — never let it take down a
        # render. Fall back to the simple voice(+music)-only mix.
        print(f"[!] Full audio mix failed, retrying without SFX (non-fatal): {exc}")
        if music:
            fc_fallback = (
                "[1:a]volume=1.0[voice];"
                "[2:a]volume=0.035,aloop=loop=-1:size=2e9[music];"
                "[voice][music]amix=inputs=2:duration=first:dropout_transition=0[aout]"
            )
            cmd_fallback = [
                "ffmpeg", "-y", "-i", str(silent_video), "-i", str(voice), "-i", str(music),
                "-filter_complex", fc_fallback,
                "-map", "0:v", "-map", "[aout]",
                *common_video, "-c:a", "aac", "-b:a", "192k", "-shortest", str(final),
            ]
        else:
            cmd_fallback = [
                "ffmpeg", "-y", "-i", str(silent_video), "-i", str(voice),
                "-map", "0:v", "-map", "1:a",
                *common_video, "-c:a", "aac", "-b:a", "192k", "-shortest", str(final),
            ]
        _run(cmd_fallback)

    if not final.exists() or final.stat().st_size < 50_000:
        raise RuntimeError("Final video was not produced correctly")

    # #10 Best-of-N thumbnail scoring from within scene 0
    thumb = OUT_DIR / "thumbnail.jpg"
    try:
        extract_best_thumbnail(final, thumb, first_scene_duration)
    except Exception as exc:
        print(f"[!] Thumbnail extraction failed (non-fatal): {exc}")

    return final
