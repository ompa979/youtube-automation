"""Premium 9:16 educational rendering with burned-in subtitles + thumbnail.

Layers per scene clip (bottom to top):
  1. Ken Burns motion on the AI image
  2. Narration subtitle strip  (y≈88%, dynamic fontsize, dark pill bg)
  3. Keyword caption            (y≈80%, ALL-CAPS, larger font)

Also extracts a thumbnail from scene 0 at 0.5 s → thumbnail.jpg in OUT_DIR.
"""
from __future__ import annotations

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


def _dynamic_fontsize(narration: str) -> int:
    """Scale subtitle font down for longer narration lines."""
    char_count = len(narration)
    if char_count < 60:
        return 48
    if char_count < 100:
        return 42
    return 36


def _wrap_subtitle(text: str, max_chars: int = 38) -> str:
    lines = textwrap.wrap(text.strip(), width=max_chars, break_long_words=False)
    return "\n".join(lines) if lines else text.strip()


def _keyword_filter(text: str) -> str:
    """Keyword/memory-cue caption at y≈80% — short ALL-CAPS label."""
    safe = _escape_drawtext(text.strip().upper())
    if not safe:
        return ""
    return (
        f"drawtext=font='Inter':text='{safe}':fontcolor=white:fontsize=58:"
        "borderw=6:bordercolor=black@0.85:box=1:boxcolor=black@0.35:boxborderw=24:"
        "x=(w-text_w)/2:y=h*0.80:line_spacing=8"
    )


def _subtitle_filter(narration: str) -> str:
    """Burned-in subtitle strip at y≈88% with dynamic font size."""
    if not narration or not narration.strip():
        return ""
    fontsize = _dynamic_fontsize(narration)
    wrapped = _wrap_subtitle(narration, max_chars=38)
    safe = _escape_drawtext(wrapped)
    if not safe:
        return ""
    return (
        f"drawtext=font='Inter':text='{safe}':fontcolor=white:fontsize={fontsize}:"
        "borderw=4:bordercolor=black@0.9:"
        "box=1:boxcolor=black@0.55:boxborderw=20:"
        "x=(w-text_w)/2:y=h*0.88:"
        "line_spacing=10"
    )


def _ken_burns_clip(
    image: Path,
    duration: float,
    out: Path,
    direction: int = 1,
    on_screen_text: str = "",
    narration: str = "",
) -> None:
    total_frames = max(int(duration * FPS), 1)
    vf = _motion_filter(direction, total_frames)

    keyword_f = _keyword_filter(on_screen_text) if on_screen_text else ""
    subtitle_f = _subtitle_filter(narration) if narration else ""

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


def extract_thumbnail(video_path: Path, out: Path, at_sec: float = 0.5) -> Path:
    """Extract a single frame from the video as a JPEG thumbnail."""
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


def _join_with_transitions(clips: list[Path], durations: list[float], out: Path) -> None:
    if len(clips) == 1:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(clips[0]), "-c", "copy", str(out)],
            check=True, capture_output=True, text=True,
        )
        return

    trans = 0.22
    inputs: list[str] = []
    for clip in clips:
        inputs += ["-i", str(clip)]

    filters = []
    current = "[0:v]"
    offset = max(durations[0] - trans, 0.05)
    for i in range(1, len(clips)):
        nxt = f"[{i}:v]"
        out_label = f"[v{i}]"
        filters.append(f"{current}{nxt}xfade=transition=fade:duration={trans}:offset={offset:.3f}{out_label}")
        current = out_label
        offset += max(durations[i] - trans, 0.05)

    cmd = [
        "ffmpeg", "-y", *inputs,
        "-filter_complex", ";".join(filters),
        "-map", current,
        "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p", str(out),
    ]
    _run(cmd)


def _concat_audio(paths: list[Path], out: Path) -> None:
    listfile = WORK_DIR / "audio_concat.txt"
    listfile.write_text("\n".join(f"file '{p.resolve()}'" for p in paths), encoding="utf-8")
    _run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
        "-c:a", "libmp3lame", "-b:a", "192k", str(out),
    ])


def _pick_music() -> Path | None:
    music_dir = ASSETS_DIR / "music"
    if not music_dir.exists():
        return None
    tracks = sorted(music_dir.glob("*.mp3")) + sorted(music_dir.glob("*.m4a"))
    return tracks[0] if tracks else None


def assemble_video(
    scene_images: list[Path],
    scene_audios: list[Path],
    scene_ass: list[Path] | None,
    scene_durations: list[float],
    slug: str,
    scene_texts: list[str] | None = None,
    scene_narrations: list[str] | None = None,
) -> Path:
    del scene_ass
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if not scene_images or not scene_audios or len(scene_images) != len(scene_audios):
        raise ValueError("Cannot render video: scene image/audio counts do not match")

    clips: list[Path] = []
    actual_durations: list[float] = []

    for i, (img, dur) in enumerate(zip(scene_images, scene_durations)):
        actual = max(float(dur), 1.0)
        clip = WORK_DIR / f"clip_{i:02d}.mp4"
        keyword = scene_texts[i] if scene_texts and i < len(scene_texts) else ""
        narration = scene_narrations[i] if scene_narrations and i < len(scene_narrations) else ""
        _ken_burns_clip(img, actual, clip, direction=i, on_screen_text=keyword, narration=narration)
        clips.append(clip)
        actual_durations.append(actual)

    silent_video = WORK_DIR / "silent_video.mp4"
    _join_with_transitions(clips, actual_durations, silent_video)

    voice = WORK_DIR / "voice.mp3"
    _concat_audio(scene_audios, voice)
    final = OUT_DIR / f"{slug}.mp4"
    music = _pick_music()

    common_video = [
        "-c:v", "libx264", "-preset", "medium", "-crf", "17",
        "-profile:v", "high", "-level", "4.2", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
    ]
    if music:
        fc = (
            "[1:a]volume=1.0[voice];"
            "[2:a]volume=0.035,aloop=loop=-1:size=2e9[music];"
            "[voice][music]amix=inputs=2:duration=first:dropout_transition=0[aout]"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", str(silent_video), "-i", str(voice), "-i", str(music),
            "-filter_complex", fc,
            "-map", "0:v", "-map", "[aout]",
            *common_video, "-c:a", "aac", "-b:a", "192k", "-shortest", str(final),
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(silent_video), "-i", str(voice),
            "-map", "0:v", "-map", "1:a",
            *common_video, "-c:a", "aac", "-b:a", "192k", "-shortest", str(final),
        ]
    _run(cmd)

    if not final.exists() or final.stat().st_size < 50_000:
        raise RuntimeError("Final video was not produced correctly")

    # Extract thumbnail from first scene at 0.5s
    thumb = OUT_DIR / "thumbnail.jpg"
    try:
        extract_thumbnail(final, thumb, at_sec=0.5)
    except Exception as exc:
        print(f"[!] Thumbnail extraction failed (non-fatal): {exc}")

    return final
