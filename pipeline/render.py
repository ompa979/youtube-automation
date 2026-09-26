"""FFmpeg-based vertical video assembly: Ken Burns + voice + captions + music."""
from __future__ import annotations

import subprocess
from pathlib import Path

from .config import WORK_DIR, OUT_DIR, ASSETS_DIR

W, H = 1080, 1920
FPS = 30

def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"Command failed ({proc.returncode}):\n{' '.join(cmd)}\n\n"
            f"--- stderr tail ---\n{proc.stderr[-2500:]}"
        )

def _ken_burns_clip(image: Path, duration: float, out: Path, direction: int = 1) -> None:
    total_frames = max(int(duration * FPS), 1)

    if direction % 2 == 0:
        z_expr = "min(1.0+0.0018*on,1.18)"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = f"ih/2-(ih/zoom/2)+{int(H*0.03)}*on/{total_frames}"
    else:
        z_expr = "max(1.18-0.0018*on,1.0)"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = f"ih/2-(ih/zoom/2)-{int(H*0.03)}*on/{total_frames}"

    vf = (
        f"scale={W*2}:{H*2}:force_original_aspect_ratio=increase,"
        f"crop={W*2}:{H*2},"
        f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}':"
        f"d={total_frames}:s={W}x{H}:fps={FPS},"
        f"format=yuv420p"
    )

    _run([
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", str(image),
        "-vf", vf,
        "-t", f"{duration:.3f}",
        "-r", str(FPS),
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        str(out),
    ])

def _concat_clips(clips: list[Path], out: Path) -> None:
    listfile = WORK_DIR / "concat.txt"
    listfile.write_text("\n".join(f"file '{c.resolve()}'" for c in clips))
    _run([
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(listfile),
        "-c", "copy",
        str(out),
    ])

def _concat_audio(paths: list[Path], out: Path) -> None:
    listfile = WORK_DIR / "audio_concat.txt"
    listfile.write_text("\n".join(f"file '{p.resolve()}'" for p in paths))
    _run([
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(listfile),
        "-c:a", "libmp3lame",
        "-b:a", "192k",
        str(out),
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
    scene_ass: list[Path],
    scene_durations: list[float],
    slug: str,
) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    clips: list[Path] = []
    for i, (img, dur) in enumerate(zip(scene_images, scene_durations)):
        clip = WORK_DIR / f"clip_{i:02d}.mp4"
        _ken_burns_clip(img, dur + 0.15, clip, direction=i)
        clips.append(clip)

    silent_video = WORK_DIR / "silent_video.mp4"
    _concat_clips(clips, silent_video)

    voice = WORK_DIR / "voice.mp3"
    _concat_audio(scene_audios, voice)

    merged_ass = WORK_DIR / "captions.ass"
    _merge_ass(scene_ass, scene_durations, merged_ass)

    final = OUT_DIR / f"{slug}.mp4"
    music = _pick_music()

    if music:
        filter_complex = (
            "[1:a]volume=1.0[voice];"
            "[2:a]volume=0.08,aloop=loop=-1:size=2e9[music];"
            "[voice][music]amix=inputs=2:duration=first:dropout_transition=0[aout]"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", str(silent_video),
            "-i", str(voice),
            "-i", str(music),
            "-filter_complex", filter_complex,
            "-map", "0:v",
            "-map", "[aout]",
            "-vf", f"ass={merged_ass}",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            str(final),
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(silent_video),
            "-i", str(voice),
            "-map", "0:v",
            "-map", "1:a",
            "-vf", f"ass={merged_ass}",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            str(final),
        ]

    _run(cmd)
    return final

def _merge_ass(scene_ass: list[Path], durations: list[float], out: Path) -> None:
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

    def parse_ts(ts: str) -> float:
        h, m, s = ts.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)

    def fmt_ts(t: float) -> str:
        h = int(t // 3600)
        m = int((t % 3600) // 60)
        s = t % 60
        return f"{h:d}:{m:02d}:{s:05.2f}"

    lines: list[str] = []
    offset = 0.0
    for ass_path, dur in zip(scene_ass, durations):
        text = ass_path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if not line.startswith("Dialogue:"):
                continue
            parts = line.split(",", 9)
            if len(parts) < 10:
                continue
            start = parse_ts(parts[1]) + offset
            end = parse_ts(parts[2]) + offset
            rest = parts[9]
            lines.append(
                f"Dialogue: 0,{fmt_ts(start)},{fmt_ts(end)},Cap,,0,0,0,,{rest}"
            )
        offset += dur + 0.15

    out.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
