"""Feed-native V20 renderer: zero TTS, four format-specific timelines, frame-0 hook."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from .config import ASSETS_DIR, OUT_DIR, WORK_DIR

W, H, FPS = 1080, 1920, 30


def _run(cmd: list[str]) -> None:
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(f"FFmpeg failed: {' '.join(cmd)}\n{p.stderr[-4000:]}")


def _esc(text: str) -> str:
    return (text or "").replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'").replace("%", "\\%")


def _sfx(name: str) -> Path | None:
    for ext in (".wav", ".mp3"):
        p = ASSETS_DIR / "sfx" / f"{name}{ext}"
        if p.exists():
            return p
    return None


def _visual_clip(image: Path, duration: float, output: Path, mode: str) -> None:
    zoom = "min(zoom+0.0028,1.16)" if mode == "push" else "max(zoom-0.0018,1.0)" if mode == "pull" else "1.08"
    x = "iw/2-(iw/zoom/2)" if mode != "pan" else "iw/2-(iw/zoom/2)+80*sin(on/35)"
    _run([
        "ffmpeg", "-y", "-loop", "1", "-i", str(image),
        "-vf", f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,zoompan=z='{zoom}':x='{x}':y='ih/2-(ih/zoom/2)':d={int(duration*FPS)}:s=1080x1920:fps={FPS}",
        "-t", f"{duration:.3f}", "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p", str(output),
    ])


def _concat(clips: list[Path], output: Path) -> None:
    manifest = WORK_DIR / "v20_concat.txt"
    manifest.write_text("".join(f"file '{p.as_posix().replace(chr(39), chr(39)+chr(92)+chr(39)+chr(39))}'\n" for p in clips), encoding="utf-8")
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(manifest), "-c", "copy", str(output)])


def render_v20_short(visual_paths: list[Path], spec: dict[str, Any], output_path: Path) -> Path:
    """Render one V20 Short. visual_paths[0] is always frame 0 and contains the hook."""
    if not visual_paths:
        raise ValueError("V20 requires at least one visual")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fmt = spec["format"]
    total = float(spec["duration_seconds"])
    t = spec["timings"]
    hook = _esc(spec["hook_text"]).replace("👁️", "").replace("💥", "").replace("🔁", "").strip()
    work_clips: list[Path] = []

    # Distinct timeline profiles; no generic countdown and no TTS.
    if fmt == "BRAIN_TRAP":
        cuts = [0.0, float(t["tension"]), float(t["reveal"]), float(t["payoff"]), total]
        modes = ["push", "pan", "push", "pull"]
    elif fmt == "SATISFYING":
        cuts = [0.0, float(t["tension"]), float(t["impact"]), float(t["aftermath"]), total]
        modes = ["push", "push", "pull", "static"]
    elif fmt == "INTERACTIVE_CHOICE":
        cuts = [0.0, 2.5, 5.0, 7.0, total]
        modes = ["static", "push", "pan", "pull"]
    else:
        cuts = [0.0, float(t["escalation"]), float(t["impossible"]), total]
        modes = ["push", "pan", "pull"]

    # Reuse generated visuals cyclically; first visual remains the native frame-0 hook.
    for i in range(len(cuts) - 1):
        dur = max(0.05, cuts[i + 1] - cuts[i])
        img = visual_paths[min(i, len(visual_paths) - 1)]
        clip = WORK_DIR / f"v20_{spec['variant']:03d}_{i:02d}.mp4"
        _visual_clip(img, dur, clip, modes[i % len(modes)])
        work_clips.append(clip)

    base = WORK_DIR / f"v20_{spec['variant']:03d}_base.mp4"
    _concat(work_clips, base)

    # Frame 0 carries both visual and bold hook. No separate thumbnail is needed.
    font_size = 86 if len(spec["hook_text"]) < 20 else 70
    vf = (
        f"drawtext=text='{hook}':font='DejaVu Sans':fontcolor=white:fontsize={font_size}:"
        "x=(w-text_w)/2:y=170:box=1:boxcolor=black@0.72:boxborderw=22:"
        "enable='between(t\\,0\\,2.8)'"
    )
    captioned = WORK_DIR / f"v20_{spec['variant']:03d}_captioned.mp4"
    _run(["ffmpeg", "-y", "-i", str(base), "-vf", vf, "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p", "-an", str(captioned)])

    # Native SFX timeline. Silence is the base; no narration track.
    sfx_files = []
    for name in spec.get("sfx", []):
        p = _sfx(name)
        if p:
            sfx_files.append(p)
    inputs = [str(captioned)] + [str(p) for p in sfx_files]
    filters = ["anullsrc=r=44100:cl=stereo,atrim=duration={:.3f}[silence]".format(total)]
    labels = ["[silence]"]
    for idx, p in enumerate(sfx_files, start=1):
        # Deterministic cue positions by format.
        cue = [0.15, float(t.get("tension", t.get("escalation", 2.0))), float(t.get("impact", t.get("impossible", 5.5))), max(0.2, total - 0.35)][min(idx - 1, 3)]
        filters.append(f"[{idx}:a]adelay={int(cue*1000)}|{int(cue*1000)},volume=0.75[a{idx}]")
        labels.append(f"[a{idx}]")
    filters.append("".join(labels) + f"amix=inputs={len(labels)}:duration=first:dropout_transition=0[a]")

    _run([
        "ffmpeg", "-y", "-i", str(captioned), *sum((["-i", p] for p in inputs[1:]), []),
        "-filter_complex", ";".join(filters), "-map", "0:v", "-map", "[a]", "-t", f"{total:.3f}",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(output_path)
    ])
    return output_path
