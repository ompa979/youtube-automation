"""Feed-native V20 renderer.

Creative invariants:
- Brain Trap / Optical Illusion / Interactive Choice: one canvas for the whole Short.
- Satisfying: real motion-video source, never a still-image substitute.
- Micro Loop: one visual canvas with deterministic ping-pong motion.
- All formats: frame-0 hook, continuous motion, native SFX, no TTS.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from .config import ASSETS_DIR, WORK_DIR

W, H, FPS = 1080, 1920, 30


def _run(cmd: list[str]) -> None:
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(f"FFmpeg failed: {' '.join(cmd)}\n{p.stderr[-5000:]}")


def sanitize_drawtext(text: str) -> str:
    return (text or "").replace("\\", "\\\\").replace("'", "’").replace(":", "\\:").replace("%", "\\%")


def get_font_param() -> str:
    for font in (
        os.getenv("V20_FONT_FILE", ""),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    ):
        if font and Path(font).exists():
            return f":fontfile='{font}'"
    return ""


def _sfx(name: str) -> Path | None:
    for ext in (".wav", ".mp3"):
        p = ASSETS_DIR / "sfx" / f"{name}{ext}"
        if p.exists():
            return p
    return None


def _audio_mix(total: float, cues: list[tuple[str, float, float]], include_bed: bool = True) -> tuple[list[str], list[str]]:
    """Return ffmpeg audio inputs and filter labels.

    Every format starts with a quiet bed; payoff SFX are independently delayed so
    the same source pad is never consumed twice.
    """
    paths: list[Path] = []
    for name, _, _ in cues:
        p = _sfx(name)
        if p:
            paths.append(p)
    filters: list[str] = []
    labels: list[str] = []
    if include_bed:
        filters.append(f"sine=frequency=55:sample_rate=44100:duration={total:.3f},volume='if(between(t,4.5,5.5),0.004,0.025)'[bed]")
        labels.append("[bed]")
    for idx, (name, cue, volume) in enumerate(cues, start=1):
        p = _sfx(name)
        if not p:
            continue
        # idx here is cue order, while ffmpeg input index starts at 1 and follows paths.
        filters.append(f"[{idx}:a]adelay={int(cue*1000)}|{int(cue*1000)},volume={volume}[s{idx}]")
        labels.append(f"[s{idx}]")
    if not labels:
        filters.append(f"anullsrc=r=44100:cl=stereo:d={total:.3f}[a]")
    else:
        filters.append("".join(labels) + f"amix=inputs={len(labels)}:duration=first:dropout_transition=0[a]")
    return [str(x) for x in paths], filters


def _render_single_canvas(visual: Path, spec: dict[str, Any], output: Path, *, choice: bool = False) -> None:
    total = float(spec["duration_seconds"])
    fmt = spec["format"]
    font = get_font_param()
    hook = sanitize_drawtext(spec["hook_text"].replace("👁️", "").replace("🔁", "").strip())

    # V20 Brain Trap is a single perceptual event. The camera starts centered,
    # continuously drifts, punches toward the declared anomaly only at payoff,
    # then returns toward the original framing for the loop. No arbitrary circle
    # or generated second image is ever introduced.
    if fmt == "BRAIN_TRAP":
        target = spec.get("target_point") or {"x": 0.50, "y": 0.50}
        tx, ty = float(target["x"]), float(target["y"])
        zoom = (
            f"if(lte(on\\,149)\\,1+0.00055*on\\," 
            f"if(lte(on\\,209)\\,1.08195+0.00113*(on-149)\\," 
            f"max(1.0\\,1.15-(0.15/30)*(on-209))))"
        )
        x = (
            f"if(lte(on\\,149)\\,iw/2-(iw/zoom/2)\\," 
            f"if(lte(on\\,209)\\,max(0\\,min(iw-iw/zoom\\,iw*{tx}-iw/(2*zoom)))\\," 
            f"iw/2-(iw/zoom/2)))"
        )
        y = (
            f"if(lte(on\\,149)\\,ih/2-(ih/zoom/2)\\," 
            f"if(lte(on\\,209)\\,max(0\\,min(ih-ih/zoom\\,ih*{ty}-ih/(2*zoom)))\\," 
            f"ih/2-(ih/zoom/2)))"
        )
    elif fmt == "OPTICAL_ILLUSION":
        zoom = r"if(lte(on\,179)\,1+0.0008*on\,1.144-(0.144/60)*(on-179))"
        x = "iw/2-(iw/zoom/2)"
        y = "ih/2-(ih/zoom/2)"
    elif choice:
        zoom = r"if(lte(on\,149)\,1.03+0.00035*on\,1.082-(0.052/90)*(on-149))"
        x = "iw/2-(iw/zoom/2)"
        y = "ih/2-(ih/zoom/2)"
    else:
        zoom = "1.06+0.00035*on"
        x = "iw/2-(iw/zoom/2)"
        y = "ih/2-(ih/zoom/2)"

    vf = (
        f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
        f"zoompan=z='{zoom}':x='{x}':y='{y}':d=240:s={W}x{H}:fps={FPS},"
        f"drawtext=text='{hook}'{font}:fontcolor=white:fontsize=84:x=(w-text_w)/2:y=150:box=1:boxcolor=black@0.72:boxborderw=20:enable='between(t\\,0\\,2)',"
    )
    if fmt == "BRAIN_TRAP":
        # Countdown lives in the lower HUD and never occludes the puzzle.
        vf += (
            f"drawtext=text='3...'{font}:fontcolor=white:fontsize=110:x=(w-text_w)/2:y=1510:box=1:boxcolor=black@0.55:boxborderw=18:enable='between(t\\,2\\,3)',"
            f"drawtext=text='2...'{font}:fontcolor=white:fontsize=110:x=(w-text_w)/2:y=1510:box=1:boxcolor=black@0.55:boxborderw=18:enable='between(t\\,3\\,4)',"
            f"drawtext=text='1...'{font}:fontcolor=red:fontsize=120:x=(w-text_w)/2:y=1510:box=1:boxcolor=black@0.55:boxborderw=18:enable='between(t\\,4\\,5)',"
        )
        if spec.get("reveal_strategy") == "PUNCH_ZOOM_TARGET":
            # The camera itself reveals the declared target; no arbitrary marker.
            vf += (
                f"drawbox=x=0:y=0:w=iw:h=ih:color=white@0.16:t=fill:enable='between(t\\,5\\,5.16)',"
                f"drawtext=text='DID YOU SEE IT?'{font}:fontcolor=white:fontsize=78:x=(w-text_w)/2:y=1510:box=1:boxcolor=black@0.68:boxborderw=18:enable='between(t\\,5.45\\,6.7)'"
            )
        else:
            vf += f"drawbox=x=0:y=0:w=iw:h=ih:color=white@0.16:t=fill:enable='between(t\\,5\\,5.16)',"
    elif fmt == "OPTICAL_ILLUSION":
        vf += f"drawtext=text='LOOK AGAIN'{font}:fontcolor=white:fontsize=72:x=(w-text_w)/2:y=1100:box=1:boxcolor=black@0.6:boxborderw=18:enable='between(t\\,5\\,7)'"
    elif choice:
        vf += (
            f"drawbox=x=40:y=400:w=1000:h=580:color=white@0.12:t=3:enable='between(t\\,0\\,8)',"
            f"drawbox=x=40:y=1000:w=1000:h=580:color=white@0.12:t=3:enable='between(t\\,0\\,8)',"
            f"drawtext=text='PICK ONE'{font}:fontcolor=white:fontsize=82:x=(w-text_w)/2:y=170:enable='between(t\\,0\\,2)',"
            f"drawtext=text='WHAT’S YOUR #1?'{font}:fontcolor=white:fontsize=68:x=(w-text_w)/2:y=1660:enable='between(t\\,6.5\\,8)'"
        )

    # Brain Trap gets an accelerating tick cadence rather than one isolated tick.
    if fmt == "BRAIN_TRAP":
        cues = [("whoosh", 0.05, 0.75)] + [("tick", t, 0.28 + i * 0.025) for i, t in enumerate((0.55, 1.15, 1.75, 2.35, 2.95, 3.45, 3.9, 4.25), start=1)] + [
            ("alert", 4.5, 0.55), ("boom", 5.5, 1.20), ("chime", 5.65, 0.75)
        ]
    else:
        cues = [("whoosh", 0.05, 0.75), ("tick", 0.55, 0.65), ("alert", 4.5, 0.55), ("boom", 5.5, 1.20), ("chime", 5.65, 0.75)]
    audio_paths, af = _audio_mix(total, cues)
    cmd = ["ffmpeg", "-y", "-loop", "1", "-i", str(visual)]
    for path in audio_paths:
        cmd += ["-i", path]
    cmd += ["-filter_complex", f"[0:v]{vf}[v];" + ";".join(af), "-map", "[v]", "-map", "[a]", "-t", f"{total:.3f}", "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(output)]
    _run(cmd)


def _render_satisfying_video(video: Path, spec: dict[str, Any], output: Path) -> None:
    total = float(spec["duration_seconds"])
    font = get_font_param()
    hook = sanitize_drawtext(spec["hook_text"].replace("💥", "").strip())
    # Real motion source: crop/scale only; no fake multi-scene substitutions.
    vf = (
        f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
        f"fps={FPS},drawtext=text='{hook}'{font}:fontcolor=white:fontsize=84:x=(w-text_w)/2:y=150:box=1:boxcolor=black@0.68:boxborderw=20:enable='between(t\\,0\\,1.7)'"
    )
    cues = [("whoosh", 0.05, 0.75), ("tick", 0.55, 0.45), ("alert", 3.55, 0.55), ("boom", 4.12, 1.35), ("chime", 4.22, 0.8)]
    audio_paths, af = _audio_mix(total, cues)
    cmd = ["ffmpeg", "-y", "-stream_loop", "-1", "-i", str(video)]
    for path in audio_paths:
        cmd += ["-i", path]
    cmd += ["-filter_complex", f"[0:v]{vf}[v];" + ";".join(af), "-map", "[v]", "-map", "[a]", "-t", f"{total:.3f}", "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(output)]
    _run(cmd)


def _render_micro_loop(visual: Path, spec: dict[str, Any], output: Path) -> None:
    total = float(spec["duration_seconds"])
    half = max(0.05, total / 2.0)
    frames = max(2, int(half * FPS))
    font = get_font_param()
    hook = sanitize_drawtext(spec["hook_text"].replace("🔁", "").strip())
    vf = (
        f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
        f"zoompan=z='min(zoom+0.002,1.15)':d={frames}:s={W}x{H}:fps={FPS},"
        "split=2[v_base][v_for_rev];[v_for_rev]reverse[v_rev];"
        f"[v_base][v_rev]concat=n=2:v=1:a=0,drawtext=text='{hook}'{font}:fontcolor=white:fontsize=84:x=(w-text_w)/2:y=150:box=1:boxcolor=black@0.65:boxborderw=20:enable='between(t\\,0\\,2)'[v]"
    )
    cues = [("whoosh", 0.05, 0.7), ("tick", 0.55, 0.5), ("alert", 5.0, 0.55), ("boom", 5.5, 1.0), ("chime", 5.65, 0.7)]
    audio_paths, af = _audio_mix(total, cues)
    cmd = ["ffmpeg", "-y", "-loop", "1", "-i", str(visual)]
    for path in audio_paths:
        cmd += ["-i", path]
    cmd += ["-filter_complex", f"[0:v]{vf};" + ";".join(af), "-map", "[v]", "-map", "[a]", "-t", f"{total:.3f}", "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(output)]
    _run(cmd)


def render_v20_short(visual_paths: list[Path], spec: dict[str, Any], output_path: Path) -> Path:
    if not visual_paths:
        raise ValueError("V20 requires a visual source")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fmt = spec["format"]
    if fmt in {"BRAIN_TRAP", "OPTICAL_ILLUSION", "INTERACTIVE_CHOICE"}:
        if len(visual_paths) != 1:
            raise ValueError(f"{fmt} requires exactly one canvas visual")
        _render_single_canvas(visual_paths[0], spec, output_path, choice=fmt == "INTERACTIVE_CHOICE")
    elif fmt == "SATISFYING":
        if len(visual_paths) != 1 or visual_paths[0].suffix.lower() not in {".mp4", ".mov", ".webm", ".m4v"}:
            raise ValueError("SATISFYING requires exactly one real motion-video source")
        _render_satisfying_video(visual_paths[0], spec, output_path)
    elif fmt == "MICRO_LOOP":
        if len(visual_paths) != 1:
            raise ValueError("MICRO_LOOP requires exactly one visual canvas")
        _render_micro_loop(visual_paths[0], spec, output_path)
    else:
        raise ValueError(f"Unsupported V20 format: {fmt}")
    return output_path
