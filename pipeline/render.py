"""Premium 9:16 educational rendering with burned-in word-by-word captions + thumbnail.

Layers per scene clip (bottom to top):
  1. Ken Burns motion on the AI image, role-driven (hook/push_in/pan_right/static)
  2. Word-by-word bold caption (bottom-anchored 170px safe margin, ONE word
                                 on screen at a time, fire-color flash -> white,
                                 pop-scale animation, timed to real or estimated
                                 per-word speech timing — see captions.py).
                                 Falls back to the old static full-sentence
                                 block subtitle if there's no timing data.
  3. Keyword caption            (y≈68%, ALL-CAPS, fire-tinted, fades in)
  4. Exam badge                 (y≈6%, small accent-tinted pill, e.g. "UPSC 2025")

Variety features (anti-monotone pass):
  #1  Accent color per SUBJECT AREA (geography/history/science/economy, detected
      from the topic text)                                -> subject_area.py
  #2  Caption box style rotates bar / pill / card (fallback path only)
  #3  Subtitle + keyword fade in instead of popping in -> alpha= expression
  #4  Semantic crossfade transitions (wipe out of hook, energetic cut into
      closing scene, zoomin for geography, radial for history) -> _semantic_transition
  #5  Background music track picked per-video by hash   -> _pick_music
  #6  Whoosh SFX on every cut + a dedicated chime on the closing-scene cut
  #7  (script_gen.py) hook style rotates per topic
  #8  (script_gen.py) prompt now asks for varied pacing
  #9  Rotating outro CTA card appended as a final "scene" -> _make_outro_clip
  #10 Thumbnail: 3+ premium 16:9 variants from an optional AI background service
      + deterministic Pillow composition + candidate scoring -> thumbnail.jpg
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import textwrap
from pathlib import Path

from .config import WORK_DIR, OUT_DIR, ASSETS_DIR
from .captions import build_word_ass
from .engagement_v2 import create_custom_thumbnail
from .motion_graphics import build_motion_graphics_filter, ensure_procedural_sfx
from .subject_area import (
    classify_subject_area,
    ACCENT_HEX,
    COLOR_GRADE,
    NICHE_BADGE,
)

W, H = 1080, 1920
FPS = 30
ENABLE_GENERIC_OUTRO = os.getenv("ENABLE_GENERIC_OUTRO", "0").strip().lower() in {"1", "true", "yes", "on"}


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"Command failed ({proc.returncode}):\n{' '.join(cmd)}\n\n"
            f"--- stderr tail ---\n{proc.stderr[-3500:]}"
        )


def _ffmpeg_supports_filter(name: str) -> bool:
    """Return whether the installed FFmpeg exposes a filter such as drawtext/ass."""
    forced = os.getenv("FORCE_NO_FFMPEG_DRAWTEXT", "").strip().lower()
    if name == "drawtext" and forced in {"1", "true", "yes", "on"}:
        return False
    try:
        proc = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            return False
        return any(line.split() and line.split()[1] == name for line in proc.stdout.splitlines() if len(line.split()) >= 2)
    except Exception:
        return False


def _stable_hash(text: str) -> int:
    """Deterministic hash (unlike Python's randomized str hash) so the same
    topic/slug always rotates to the same style — reproducible renders,
    but different topics land on different styles/colors/tracks."""
    return int(hashlib.md5(text.encode("utf-8")).hexdigest(), 16)


# ---------------------------------------------------------------------------
# #1 Accent color — now keyed by SUBJECT AREA (geography/history/science/
# economy, detected from the topic text — see subject_area.py) rather than
# just the niche. Two videos in the same niche ("exam_concepts") but about a
# monsoon-wind question vs. a fiscal-deficit question now get genuinely
# different accent colors, grades and prompt styles instead of looking
# identical because they share a niche key.
# ---------------------------------------------------------------------------
ACCENT_PALETTE = ACCENT_HEX  # kept as an alias — legacy call sites still work


def _accent_for_subject_area(subject_area: str) -> str:
    return ACCENT_HEX.get(subject_area, ACCENT_HEX["default"])


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


# ---------------------------------------------------------------------------
# #5 Motion — now driven by the scene's narrative ROLE, not an arbitrary
# rotating index, so the camera move actually means something:
#   "hook"      — pull BACK (start zoomed in, ease out to reveal)  — scene 0
#   "push_in"   — push IN (default "explanation" beat)             — middle scenes
#   "pan_right" — lateral pan, no zoom change                      — geography videos
#   "static"    — barely moves, forces the eye to read the caption — the
#                 closing "exam tip" scene (last narration scene)
# ---------------------------------------------------------------------------
def _motion_filter(role: str, total_frames: int, subject_area: str = "default") -> str:
    n = max(total_frames, 1)
    if role in ("hook", "shake_and_push"):
        z = f"1.16-0.16*on/{n}"
        x = f"iw/2-(iw/zoom/2)-30*on/{n}"
        y = "ih/2-(ih/zoom/2)"
    elif role in ("snap_zoom", "push_fast"):
        z = f"1.00+0.18*on/{n}"
        x = "iw/2-(iw/zoom/2)"
        y = f"ih/2-(ih/zoom/2)+45*on/{n}"
    elif role in ("pan_right", "pan_subtle"):
        z = "1.10"
        x = f"iw/2-(iw/zoom/2)-70*on/{n}"
        y = "ih/2-(ih/zoom/2)"
    elif role == "static":
        z = f"1.00+0.03*on/{n}"
        x = "iw/2-(iw/zoom/2)"
        y = "ih/2-(ih/zoom/2)"
    else:  # "push_in" — default explanation beat
        z = f"1.00+0.13*on/{n}"
        x = "iw/2-(iw/zoom/2)"
        y = f"ih/2-(ih/zoom/2)+40*on/{n}"

    grade = COLOR_GRADE.get(subject_area, COLOR_GRADE["default"])
    return (
        f"scale={W*2}:{H*2}:force_original_aspect_ratio=increase,"
        f"crop={W*2}:{H*2},"
        f"zoompan=z='{z}':x='{x}':y='{y}':d={total_frames}:s={W}x{H}:fps={FPS},"
        f"{grade},"
        # Layer 5 finishing pass: cinematic vignette + light film grain to
        # cut the flat "AI-plastic" look of a raw Flux/Pollinations frame.
        "vignette=PI/4.3,"
        "noise=alls=6:allf=t+u,"
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


# Layer 2, tier 2: the "fire" keyword color — a hot orange-red that reads
# instantly against every subject-area color grade (teal, sepia, violet or
# grey) and is what makes the keyword feel like the thing worth screenshotting.
_FIRE_COLOR = "0xFF4A1F"


def _keyword_filter(text: str) -> str:
    """Keyword/memory-cue caption at y≈68% — short ALL-CAPS label in the
    fire color, with a dark box so it stays legible over any background."""
    safe = _escape_drawtext(text.strip().upper())
    if not safe:
        return ""
    return (
        f"drawtext=font='Inter':text='{safe}':fontcolor={_FIRE_COLOR}:fontsize=60:"
        f"borderw=6:bordercolor=black@0.9:box=1:boxcolor=black@0.40:boxborderw=24:"
        f"x=(w-text_w)/2:y=h*0.68:line_spacing=8:{_FADE_IN_ALPHA}"
    )


# Layer 2, tier 1: the small "exam badge" pill near the top of frame —
# e.g. "UPSC 2025" — that brands every scene without competing with the
# keyword or subtitle for attention.
def _badge_filter(badge_text: str, accent: str) -> str:
    safe = _escape_drawtext(badge_text.strip().upper())
    if not safe:
        return ""
    return (
        f"drawtext=font='Inter':text='{safe}':fontcolor=white:fontsize=30:"
        f"borderw=2:bordercolor=black@0.8:box=1:boxcolor={accent}@0.85:boxborderw=14:"
        f"x=(w-text_w)/2:y=h*0.06:{_FADE_IN_ALPHA}"
    )


def _memory_anchor_filter(text: str, accent: str) -> str:
    """Glassmorphic memory-anchor card at Y≈32% — shows the exam trick/rule.

    This is the 'bullet note' the user misses from text_card mode. It renders
    the LLM-generated `card_points[0]` (e.g. '3NF: KILL TRANSITIVE DEPENDENCY')
    as a compact, accent-bordered semi-transparent card above the karaoke
    captions so viewers see the key takeaway on every scene.
    """
    raw = " ".join((text or "").split()).upper()
    if not raw:
        return ""
    # Hard-cap to 50 chars so the card stays compact and readable
    if len(raw) > 50:
        raw = raw[:50].rsplit(" ", 1)[0]
    safe = _escape_drawtext(raw)
    if not safe:
        return ""
    return (
        f"drawtext=font='Inter':text='\u26a1 {safe}':"
        f"fontcolor=white:fontsize=34:"
        f"borderw=3:bordercolor=black@0.85:"
        f"box=1:boxcolor=black@0.50:boxborderw=14|28|14|28:"
        f"x=(w-text_w)/2:y=h*0.32:"
        f"line_spacing=8:{_FADE_IN_ALPHA}"
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


def _ass_filter_arg(ass_path: Path) -> str:
    """Escape a path for use as the ffmpeg `ass=` filter argument."""
    p = str(ass_path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    return f"ass='{p}'"


def _ken_burns_clip(
    image: Path,
    duration: float,
    out: Path,
    role: str = "push_in",
    on_screen_text: str = "",
    narration: str = "",
    caption_style: str = "bar",
    accent: str = ACCENT_PALETTE["default"],
    subject_area: str = "default",
    badge_text: str = "",
    word_timings: list[dict] | None = None,
    scene_index: int = 0,
    total_scenes: int = 1,
    anchor_text: str = "",
    action_type: str = "explanation",
    action_payload: str = "",
) -> None:
    total_frames = max(int(duration * FPS), 1)
    vf = _motion_filter(role, total_frames, subject_area)

    # Motion graphics overlay — progress bar, vignette pulse, rule line,
    # hook sweep, scene dots, and dedicated Action HUD.
    drawtext_ok = _ffmpeg_supports_filter("drawtext")
    mg_f = build_motion_graphics_filter(
        duration=duration,
        accent=accent,
        scene_index=scene_index,
        total_scenes=total_scenes,
        is_hook=(role == "hook"),
        action_type=action_type,
        action_payload=action_payload,
        allow_drawtext=drawtext_ok,
    )
    if mg_f:
        vf = f"{vf},{mg_f}"

    # Layer 2: 4-layer on-screen text system — exam badge (top), memory
    # anchor card (≈32%), fire-tinted keyword (mid), and a word-by-word
    # bold caption (bottom).
    interactive_beats = {"pattern_interrupt", "challenge", "countdown", "reveal", "mechanism", "trap_loop", "loop", "trap", "hook", "context", "example", "exam_takeaway", "memory_lock"}
    badge_f = _badge_filter(badge_text, accent) if drawtext_ok and badge_text and on_screen_text else ""
    # In V2 the Action HUD is the primary visual interface. Stacking an extra
    # keyword and memory card on every interactive scene made the frame look
    # like a study poster and buried the actual question.
    anchor_f = _memory_anchor_filter(anchor_text, accent) if drawtext_ok and anchor_text and action_type not in interactive_beats else ""
    keyword_f = _keyword_filter(on_screen_text) if drawtext_ok and on_screen_text and action_type not in interactive_beats else ""

    if badge_f:
        vf = f"{vf},{badge_f}"
    if anchor_f:
        vf = f"{vf},{anchor_f}"
    if keyword_f:
        vf = f"{vf},{keyword_f}"

    # Try word-by-word ASS karaoke captions first; fall back to the old
    # single-block subtitle if there's no usable word timing, or if this
    # ffmpeg build turns out not to have libass, in which case the run
    # below throws and we retry once with the block-subtitle filter instead
    # of failing the whole render.
    ass_path = out.with_suffix(".ass")
    has_words = bool(narration) and build_word_ass(word_timings, duration, ass_path)
    vf_words = f"{vf},{_ass_filter_arg(ass_path)}" if has_words else vf

    fallback_subtitle_f = _subtitle_filter(narration, caption_style, accent) if drawtext_ok and narration else ""
    vf_fallback = f"{vf},{fallback_subtitle_f}" if fallback_subtitle_f else vf

    if not drawtext_ok:
        print("[render] FFmpeg drawtext unavailable; using ASS captions + drawbox-only motion graphics")

    cmd = [
        "ffmpeg", "-y", "-loop", "1", "-i", str(image),
        "-vf", vf_words, "-t", f"{duration:.3f}", "-r", str(FPS),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        "-profile:v", "high", "-level", "4.2", "-pix_fmt", "yuv420p", str(out),
    ]
    if has_words:
        try:
            _run(cmd)
            return
        except Exception as exc:
            print(f"[!] word-by-word ASS captions failed (falling back to block subtitle): {exc}")

    cmd[cmd.index("-vf") + 1] = vf_fallback
    _run(cmd)


# ---------------------------------------------------------------------------
# #9 Rotating outro CTA card — appended as a final "scene" before joining
# ---------------------------------------------------------------------------
CTA_PHRASES = [
    "Comment your answer below",
    "What should we explain next? Comment below",
    "Comment your answer below",
    "Which exam are you preparing for? Comment",
    "Comment DONE if you learned this",
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
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        "-profile:v", "high", "-level", "4.2", "-pix_fmt", "yuv420p", str(out),
    ])


# ---------------------------------------------------------------------------
# #4 Loopability — a short closing beat that visually echoes scene 0, so the
# video's last frame rhymes with its first. On Shorts this is a genuine
# rewatch cue: "replay value" is one of the four core ranking signals, and a
# video that loops cleanly back into itself gets rewatched more than one
# that just stops.
# ---------------------------------------------------------------------------
def _make_loopback_clip(
    image: Path, keyword_text: str, accent: str, out: Path, duration: float = 0.6
) -> None:
    total_frames = max(int(duration * FPS), 1)
    # Deliberately near-static (tiny zoom only) so it reads as "back to the
    # start" rather than a new scene with its own motion.
    vf = (
        f"scale={W*2}:{H*2}:force_original_aspect_ratio=increase,"
        f"crop={W*2}:{H*2},"
        f"zoompan=z='1.00':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={total_frames}:s={W}x{H}:fps={FPS},"
        "eq=contrast=1.045:saturation=1.035:brightness=0.004,format=yuv420p"
    )
    keyword_f = _keyword_filter(keyword_text) if _ffmpeg_supports_filter("drawtext") and keyword_text else ""
    if keyword_f:
        vf = f"{vf},{keyword_f}"
    _run([
        "ffmpeg", "-y", "-loop", "1", "-i", str(image),
        "-vf", vf, "-t", f"{duration:.3f}", "-r", str(FPS),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
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
    """Enhanced content-aware thumbnail scoring (V3).
    Rewards:
      - High edge density (indicates sharp, readable on-screen text and graphic elements)
      - High dynamic range / contrast (pop on small mobile screens)
      - Rich color saturation (stands out in YouTube feed)
    Penalizes:
      - Crushed dark frames (mean < 35) or blown-out frames (mean > 215)
    """
    try:
        from PIL import Image, ImageFilter, ImageStat
        with Image.open(path) as img:
            rgb = img.convert("RGB").resize((180, 320))
            gray = rgb.convert("L")

            # 1. Edge density / text sharpness (find edges filter)
            edges = gray.filter(ImageFilter.FIND_EDGES)
            edge_stat = ImageStat.Stat(edges)
            edge_score = edge_stat.mean[0]

            # 2. Luminance & Contrast
            gray_stat = ImageStat.Stat(gray)
            mean_lum = gray_stat.mean[0]
            contrast = gray_stat.stddev[0]

            # Brightness penalty: ideal midtone is ~120
            lum_penalty = max(0.2, 1.0 - abs(mean_lum - 120) / 100.0)

            # 3. Colorfulness / saturation
            r, g, b = rgb.split()
            r_stat, g_stat, b_stat = ImageStat.Stat(r), ImageStat.Stat(g), ImageStat.Stat(b)
            colorfulness = (r_stat.stddev[0] + g_stat.stddev[0] + b_stat.stddev[0]) / 3.0

            # Composite score (heavily rewards text edge sharpness + contrast)
            final_score = (contrast * 1.2) + (edge_score * 2.2) + (colorfulness * 0.8)
            final_score *= lum_penalty
            return float(final_score)
    except Exception as exc:
        print(f"[render] _score_frame error: {exc}")
        return 50.0


def extract_best_thumbnail(video_path: Path, out: Path, scene0_duration: float) -> Path:
    """Sample several candidate frames from within scene 0 and keep whichever
    scores best for contrast/brightness, instead of always grabbing whatever
    happened to be on screen at a fixed 0.5s.

    #6: candidates start at 0.42s (just after the 0.35s keyword/subtitle
    fade-in completes), not 0.15s — a thumbnail grabbed mid-fade shows faint,
    half-opacity text, which defeats the point of having on-screen keywords
    for search/Lens-readable thumbnails in the first place.
    """
    fade_clear = 0.42
    hi = max(fade_clear + 0.05, min(scene0_duration - 0.15, 1.9))
    if scene0_duration - 0.15 < fade_clear:
        # Scene 0 is too short for the fade to fully clear — fall back to
        # whatever's latest and accept a slightly softer keyword.
        candidate_times = [max(0.15, scene0_duration - 0.2)]
    else:
        n = 4
        candidate_times = [fade_clear + i * (hi - fade_clear) / (n - 1) for i in range(n)]

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
# #4 Transitions that carry meaning, not just a round-robin rotation:
#   - the cut OUT of the hook (scene 0 -> scene 1)              -> wiperight
#   - the cut INTO the final challenge/loop scene                -> smoothleft
#   - every other cut in a GEOGRAPHY video                       -> zoomin
#   - every other cut in a HISTORY video                         -> radial
#   - everything else (science/economy/default)                  -> rotates
#     through a small neutral pool so it's still varied
# ---------------------------------------------------------------------------
_NEUTRAL_TRANSITIONS = ["fade", "dissolve", "smoothleft", "circlecrop"]


def _semantic_transition(cut_index: int, num_narration_scenes: int, subject_area: str) -> str:
    """cut_index is 0-based over ALL joins (scene cuts + outro + loopback).
    num_narration_scenes is how many of the joined clips are real narration
    scenes (i.e. excludes the appended outro/loopback clips)."""
    # Cut OUT of the hook: clip 0 -> clip 1 is cut_index 0.
    if cut_index == 0:
        return "wiperight"
    # Cut INTO the last narration scene (the "exam tip" beat): that's the
    # join whose result is clip index (num_narration_scenes - 1), i.e.
    # cut_index == num_narration_scenes - 2.
    if num_narration_scenes >= 2 and cut_index == num_narration_scenes - 2:
        return "smoothleft"
    if subject_area == "geography":
        return "zoomin"
    if subject_area == "history":
        return "radial"
    return _NEUTRAL_TRANSITIONS[cut_index % len(_NEUTRAL_TRANSITIONS)]


def _join_with_transitions(
    clips: list[Path], durations: list[float], out: Path,
    num_narration_scenes: int = 0, subject_area: str = "default",
) -> list[float]:
    """Joins clips with a semantically-chosen crossfade transition per cut
    (see _semantic_transition). Returns the list of cut center-times
    (seconds, in the joined timeline) — used to time the whoosh/chime SFX
    so they land exactly on each visual cut."""
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
        t_type = _semantic_transition(i - 1, num_narration_scenes, subject_area)
        filters.append(f"{current}{nxt}xfade=transition={t_type}:duration={trans}:offset={offset:.3f}{out_label}")
        cut_offsets.append(offset + trans / 2)
        current = out_label
        offset += max(durations[i] - trans, 0.05)

    cmd = [
        "ffmpeg", "-y", *inputs,
        "-filter_complex", ";".join(filters),
        "-map", current,
        "-c:v", "libx264", "-preset", "medium", "-crf", "22", "-pix_fmt", "yuv420p", str(out),
    ]
    _run(cmd)
    return cut_offsets


def _concat_audio(paths: list[Path], out: Path) -> None:
    listfile = WORK_DIR / "audio_concat.txt"
    listfile.write_text("\n".join(f"file '{p.resolve()}'" for p in paths), encoding="utf-8")
    _run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
        "-c:a", "libmp3lame", "-b:a", "160k", str(out),
    ])


def _probe_duration(path: Path) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True,
    )
    return float(proc.stdout.strip())


# ---------------------------------------------------------------------------
# #5 Music: mood-aware rotation (best feasible substitute for true trending-
# audio integration — there is no public API for "what sound is trending on
# Shorts right now", so this instead matches track energy to the niche/topic,
# then still rotates by slug hash within that mood so it's not always the
# same file. If you want real trending-audio integration, that requires
# manually downloading a licensed trending clip and dropping it in
# assets/music/ — see assets/music/README.md.
# ---------------------------------------------------------------------------
_MOOD_TRACKS: dict[str, list[str]] = {
    "upbeat": ["upbeat_1.mp3"],
    "calm": ["ambient_soft_1.mp3", "lofi_study_1.mp3"],
}
_NICHE_MOOD: dict[str, str] = {
    "bank_it_officer": "calm",
    "bank_reasoning_quant": "upbeat",
    "banking_awareness": "calm",
    "rbi_economy": "calm",
    "bank_english": "calm",
    "exam_concepts": "calm",
    "science_explainers": "upbeat",
    "default": "calm",
}


def _pick_music(seed: str | None = None, category: str | None = None) -> Path | None:
    music_dir = ASSETS_DIR / "music"
    if not music_dir.exists():
        return None
    all_tracks = sorted(music_dir.glob("*.mp3")) + sorted(music_dir.glob("*.m4a"))
    if not all_tracks:
        return None
    if seed is None:
        return all_tracks[0]
    mood = _NICHE_MOOD.get(category or "", "calm")
    mood_files = set(_MOOD_TRACKS.get(mood, []))
    candidates = [t for t in all_tracks if t.name in mood_files] or all_tracks
    return candidates[_stable_hash(seed) % len(candidates)]


# ---------------------------------------------------------------------------
# #6 Whoosh SFX at every scene cut, + a dedicated "exam tip" chime
# ---------------------------------------------------------------------------
def _pick_sfx() -> Path | None:
    sfx_dir = ASSETS_DIR / "sfx"
    if not sfx_dir.exists():
        return None
    tracks = sorted(sfx_dir.glob("*.mp3")) + sorted(sfx_dir.glob("*.wav"))
    tracks = [t for t in tracks if t.stem != "chime"]
    return tracks[0] if tracks else None


def _pick_chime() -> Path | None:
    """A short two-note chime layered once, right as the closing 'exam tip'
    scene begins. Pavlovian by design: after a few videos, viewers who
    recognize the chime start paying closer attention right when it hits,
    because it always means "the takeaway is coming"."""
    chime = ASSETS_DIR / "sfx" / "chime.mp3"
    return chime if chime.exists() else None


def _pick_sfx_by_name(name: str) -> Path | None:
    sfx_dir = ASSETS_DIR / "sfx"
    if not sfx_dir.exists():
        return None
    stem = name.strip().lower()
    for ext in (".wav", ".mp3"):
        candidate = sfx_dir / f"{stem}{ext}"
        if candidate.exists():
            return candidate
    return None


def assemble_video(
    scene_images: list[Path],
    scene_audios: list[Path],
    scene_ass: list[Path] | None,
    scene_durations: list[float],
    slug: str,
    scene_texts: list[str] | None = None,
    scene_narrations: list[str] | None = None,
    category: str = "default",
    topic: str = "",
    scene_word_timings: list[list[dict]] | None = None,
    scene_card_points: list[list[str]] | None = None,
    scene_action_types: list[str] | None = None,
    scene_action_payloads: list[str] | None = None,
    scene_motion_types: list[str] | None = None,
    scene_camera_motions: list[str] | None = None,
    scene_sfx_cues: list[str] | None = None,
    thumbnail_text: str = "",
    thumbnail_label: str = "EXAMCRACKER AI",
    thumbnail_subline: str = "",
    thumbnail_visual_prompt: str = "",
) -> Path:
    del scene_ass
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        ensure_procedural_sfx(ASSETS_DIR / "sfx")
    except Exception:
        pass
    if not scene_images or not scene_audios or len(scene_images) != len(scene_audios):
        raise ValueError("Cannot render video: scene image/audio counts do not match")

    # Subject area drives accent/grade/prompt-style/transitions/motion for
    # this whole video — see subject_area.py.
    subject_area = classify_subject_area(topic)
    accent = _accent_for_subject_area(subject_area)
    badge_text = NICHE_BADGE.get(category, NICHE_BADGE["default"])
    num_narration_scenes = len(scene_images)

    clips: list[Path] = []
    actual_durations: list[float] = []

    for i, (img, dur) in enumerate(zip(scene_images, scene_durations)):
        actual = max(float(dur), 1.0)
        clip = WORK_DIR / f"clip_{i:02d}.mp4"
        keyword = scene_texts[i] if scene_texts and i < len(scene_texts) else ""
        narration = scene_narrations[i] if scene_narrations and i < len(scene_narrations) else ""
        word_timings = (
            scene_word_timings[i] if scene_word_timings and i < len(scene_word_timings) else None
        )
        # Memory anchor text from card_points[0] for the glassmorphic overlay
        anchor_text = ""
        if scene_card_points and i < len(scene_card_points):
            pts = scene_card_points[i]
            if pts and isinstance(pts, list) and len(pts) > 0:
                anchor_text = str(pts[0]).strip()
        style = _CAPTION_STYLES[i % len(_CAPTION_STYLES)]

        act_type = (
            scene_action_types[i]
            if scene_action_types and i < len(scene_action_types)
            else "explanation"
        )
        act_payload = (
            scene_action_payloads[i]
            if scene_action_payloads and i < len(scene_action_payloads)
            else ""
        )
        if not act_payload and anchor_text:
            act_payload = anchor_text

        # Layer 5 role: hook / static("exam tip") / pan_right(geography) / push_in(default)
        if scene_camera_motions and i < len(scene_camera_motions) and scene_camera_motions[i]:
            role = scene_camera_motions[i]
        elif i == 0:
            role = "hook"
        elif i == num_narration_scenes - 1 and num_narration_scenes >= 2:
            role = "static"
        elif subject_area == "geography":
            role = "pan_right"
        else:
            role = "push_in"

        _ken_burns_clip(
            img, actual, clip, role=role, on_screen_text=keyword, narration=narration,
            caption_style=style, accent=accent, subject_area=subject_area, badge_text=badge_text,
            word_timings=word_timings,
            scene_index=i, total_scenes=num_narration_scenes,
            anchor_text=anchor_text,
            action_type=act_type,
            action_payload=act_payload,
        )
        clips.append(clip)
        actual_durations.append(actual)

    first_scene_duration = actual_durations[0] if actual_durations else 1.0

    # V2: no generic CTA card between the final challenge and the loop.
    # It created a visible "video over" break. Legacy behavior remains opt-in.
    if ENABLE_GENERIC_OUTRO:
        outro_clip = WORK_DIR / "clip_outro.mp4"
        cta_text = _pick_cta(slug)
        outro_duration = 1.0
        try:
            _make_outro_clip(accent, cta_text, outro_clip, duration=outro_duration)
            clips.append(outro_clip)
            actual_durations.append(outro_duration)
        except Exception as exc:
            print(f"[!] Legacy outro card failed (non-fatal, skipping): {exc}")

    # #4 Loopability: close on scene 0's frame + keyword again, so the video
    # ends where it began instead of just stopping on the CTA.
    if scene_images:
        loopback_clip = WORK_DIR / "clip_loopback.mp4"
        loop_keyword = scene_texts[0] if scene_texts else ""
        try:
            _make_loopback_clip(scene_images[0], loop_keyword, accent, loopback_clip, duration=0.35)
            clips.append(loopback_clip)
            actual_durations.append(0.6)
        except Exception as exc:
            print(f"[!] Loopback clip failed (non-fatal, skipping): {exc}")

    silent_video = WORK_DIR / "silent_video.mp4"
    cut_offsets = _join_with_transitions(
        clips, actual_durations, silent_video,
        num_narration_scenes=num_narration_scenes, subject_area=subject_area,
    )
    total_video_duration = _probe_duration(silent_video)

    # Trigger distinct chime on reveal scene if present, otherwise on closing tip cut
    chime_offset: float | None = None
    if scene_action_types:
        for idx, act in enumerate(scene_action_types):
            if act == "reveal" and idx > 0 and idx - 1 < len(cut_offsets):
                chime_offset = cut_offsets[idx - 1]
                break
    if chime_offset is None and num_narration_scenes >= 2 and len(cut_offsets) >= num_narration_scenes - 1:
        chime_offset = cut_offsets[num_narration_scenes - 2]

    voice_raw = WORK_DIR / "voice_raw.mp3"
    _concat_audio(scene_audios, voice_raw)
    # BUG FIX: the outro card + loopback clip play AFTER the narration ends,
    # so the voice track is shorter than the full video. Downstream we mix
    # with duration=first(=voice) and mux with -shortest, so without this
    # pad, the outro/loopback would get silently truncated off the final
    # render — pad the voice track with silence out to the full video
    # length so nothing after the last spoken line gets cut.
    voice = WORK_DIR / "voice.mp3"
    _run([
        "ffmpeg", "-y", "-i", str(voice_raw),
        "-af", f"apad=whole_dur={total_video_duration:.3f}",
        "-c:a", "libmp3lame", "-b:a", "160k", str(voice),
    ])

    final = OUT_DIR / f"{slug}.mp4"
    music = _pick_music(seed=slug, category=category)
    sfx = _pick_sfx() if cut_offsets else None

    common_video = [
        "-c:v", "libx264", "-preset", "medium", "-crf", "22",
        "-profile:v", "high", "-level", "4.2", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
    ]

    # Build the audio graph: voice (always) + music (optional, ducked +
    # looped) + one delayed/ducked whoosh hit per scene cut (optional).
    audio_inputs = [voice]
    parts = ["[1:a]volume=2.00,aformat=channel_layouts=stereo[voice]"]
    mix_labels = ["[voice]"]
    next_idx = 2

    if music:
        audio_inputs.append(music)
        parts.append(
            f"[{next_idx}:a]volume=0.015,aloop=loop=-1:size=2e9,aformat=channel_layouts=stereo[music]"
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
                f"[{sfx_idx}:a]adelay={ms}|{ms},volume=0.16,aformat=channel_layouts=stereo{label}"
            )
            mix_labels.append(label)

    # #6 Exam-tip chime — one short, distinct hit layered exactly at the cut
    # into the closing scene, separate from (and slightly louder than) the
    # generic whoosh so it reads as its own recurring cue.
    chime = _pick_chime() if chime_offset is not None else None
    if chime:
        audio_inputs.append(chime)
        chime_idx = next_idx
        next_idx += 1
        ms = max(int(chime_offset * 1000), 0)
        parts.append(
            f"[{chime_idx}:a]adelay={ms}|{ms},volume=0.24,aformat=channel_layouts=stereo[chime]"
        )
        mix_labels.append("[chime]")

    # Named SFX per scene (tick, alert, boom)
    if scene_sfx_cues and cut_offsets:
        named_loaded: dict[str, int] = {}
        scene_starts = [0.0] + list(cut_offsets[:num_narration_scenes - 1])
        for s_idx, (cue_name, s_off) in enumerate(zip(scene_sfx_cues, scene_starts)):
            if not cue_name or cue_name in ("whoosh", "chime"):
                continue
            s_path = _pick_sfx_by_name(cue_name)
            if not s_path:
                continue
            if cue_name not in named_loaded:
                audio_inputs.append(s_path)
                named_loaded[cue_name] = next_idx
                next_idx += 1
            s_idx_in = named_loaded[cue_name]
            vol = {"boom": 0.28, "tick": 0.18, "alert": 0.22}.get(cue_name, 0.20)
            d_ms = max(int(s_off * 1000), 0)
            lbl = f"[sfx_{s_idx}_{cue_name}]"
            parts.append(f"[{s_idx_in}:a]adelay={d_ms}|{d_ms},volume={min(vol,0.18)},aformat=channel_layouts=stereo{lbl}")
            mix_labels.append(lbl)

    parts.append(f"{''.join(mix_labels)}amix=inputs={len(mix_labels)}:duration=first:dropout_transition=0,loudnorm=I=-13:TP=-1.0:LRA=7,alimiter=limit=0.95:attack=5:release=50[aout]")
    fc = ";".join(parts)

    cmd = [
        "ffmpeg", "-y", "-i", str(silent_video),
    ]
    for p in audio_inputs:
        cmd += ["-i", str(p)]
    cmd += [
        "-filter_complex", fc,
        "-map", "0:v", "-map", "[aout]",
        *common_video, "-c:a", "aac", "-b:a", "160k", "-shortest", str(final),
    ]

    try:
        _run(cmd)
    except Exception as exc:
        # Whoosh/music mixing is a nice-to-have — never let it take down a
        # render. Fall back to the simple voice(+music)-only mix.
        print(f"[!] Full audio mix failed, retrying without SFX (non-fatal): {exc}")
        if music:
            fc_fallback = (
                "[1:a]volume=2.00[voice];"
                "[2:a]volume=0.015,aloop=loop=-1:size=2e9[music];"
                "[voice][music]amix=inputs=2:duration=first:dropout_transition=0,loudnorm=I=-13:TP=-1.0:LRA=7,alimiter=limit=0.95:attack=5:release=50[aout]"
            )
            cmd_fallback = [
                "ffmpeg", "-y", "-i", str(silent_video), "-i", str(voice), "-i", str(music),
                "-filter_complex", fc_fallback,
                "-map", "0:v", "-map", "[aout]",
                *common_video, "-c:a", "aac", "-b:a", "160k", "-shortest", str(final),
            ]
        else:
            cmd_fallback = [
                "ffmpeg", "-y", "-i", str(silent_video), "-i", str(voice),
                "-map", "0:v", "-map", "1:a",
                *common_video, "-c:a", "aac", "-b:a", "160k", "-shortest", str(final),
            ]
        _run(cmd_fallback)

    if not final.exists() or final.stat().st_size < 50_000:
        raise RuntimeError("Final video was not produced correctly")

    # V2 packaging: build a true 16:9 custom thumbnail from the challenge beat.
    # The previous implementation uploaded a 9:16 video frame, which is the wrong
    # composition for conventional YouTube thumbnail surfaces.
    thumb = OUT_DIR / "thumbnail.jpg"
    try:
        challenge_offset = min(
            max(first_scene_duration + 0.55, 0.65),
            max(total_video_duration - 0.45, 0.65),
        )
        thumb_text = thumbnail_text or (scene_texts[0] if scene_texts and scene_texts[0] else "KEY IDEA")
        clean_background = scene_images[1] if len(scene_images) > 1 else scene_images[0]
        create_custom_thumbnail(
            final,
            thumb,
            challenge_offset,
            thumb_text,
            thumbnail_label or badge_text,
            background_path=clean_background,
            topic=topic,
            subline=thumbnail_subline,
            visual_prompt=thumbnail_visual_prompt,
        )
        print(f"[render] V7 16:9 premium thumbnail created: {thumb} ({thumb.stat().st_size // 1024}KB)")
    except Exception as exc:
        print(f"[!] V2 thumbnail failed, falling back to best frame: {exc}")
        try:
            extract_best_thumbnail(final, thumb, first_scene_duration)
        except Exception as fallback_exc:
            print(f"[!] Thumbnail fallback also failed (non-fatal): {fallback_exc}")

    return final
