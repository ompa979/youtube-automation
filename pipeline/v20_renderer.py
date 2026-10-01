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


def sanitize_drawtext(text: str) -> str:
    """Escape text for FFmpeg drawtext filter syntax."""
    return (text or "").replace("\\", "\\\\").replace("'", "’").replace(":", "\\:").replace("%", "\\%")


def get_font_param() -> str:
    """Resolve a deterministic bold font on GitHub-hosted Ubuntu runners."""
    candidates = [
        os.getenv("V20_FONT_FILE", ""),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    ]
    for font in candidates:
        if font and Path(font).exists():
            return f":fontfile='{font.replace(chr(39), chr(92)+chr(39))}'"
    return ""


def _esc(text: str) -> str:
    # Backward-compatible alias used by the renderer.
    return sanitize_drawtext(text)


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


def _render_micro_loop(visual: Path, duration: float, output: Path) -> None:
    """Render a forward/reverse ping-pong visual with an explicit split branch."""
    half = max(0.05, duration / 2.0)
    frames = max(2, int(half * FPS))
    filtergraph = (
        f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
        f"zoompan=z='min(zoom+0.002,1.15)':d={frames}:s={W}x{H}:fps={FPS},"
        "split=2[v_base][v_for_rev];"
        "[v_for_rev]reverse[v_rev];"
        "[v_base][v_rev]concat=n=2:v=1:a=0[v]"
    )
    _run([
        "ffmpeg", "-y", "-loop", "1", "-i", str(visual),
        "-filter_complex", filtergraph, "-map", "[v]",
        "-t", f"{duration:.3f}", "-an", "-c:v", "libx264", "-preset", "fast",
        "-crf", "20", "-pix_fmt", "yuv420p", str(output),
    ])


def _render_brain_trap_single_canvas(visual: Path, spec: dict[str, Any], output: Path) -> None:
    """Render the Brain Trap as one continuous canvas with a real reveal and reset.

    Timeline:
      0.0-2.0  immediate visual + hook + riser
      2.0-5.0  3/2/1 countdown + ticks
      5.0-7.0  target highlight + punch emphasis + boom
      7.0-8.0  camera returns to the exact frame-0 zoom for looping
    """
    total = 8.0
    font = get_font_param()
    hook = sanitize_drawtext(spec["hook_text"].replace("👁️", "").strip())
    # The prompt fixes the odd eye around x=65%, y=50%. The ring is therefore
    # anchored to the same deterministic center-safe location.
    ring = "drawtext=text='◯':fontcolor=red:fontsize=270" + font + ":x=w*0.535:y=h*0.39:enable='between(t\\,5\\,7)'"
    vf = (
        f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
        f"zoompan=z='if(lte(on\\,209)\\,1+0.00055*on\\,1.115-(0.115/30)*(on-209))':"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=240:s={W}x{H}:fps={FPS},"
        f"drawtext=text='{hook}'{font}:fontcolor=white:fontsize=86:"
        f"x=(w-text_w)/2:y=170:box=1:boxcolor=black@0.72:boxborderw=22:"
        f"enable='between(t\\,0\\,2)' ,"
        f"drawtext=text='3...'{font}:fontcolor=white:fontsize=110:x=(w-text_w)/2:y=790:"
        f"box=1:boxcolor=black@0.55:boxborderw=18:enable='between(t\\,2\\,3)' ,"
        f"drawtext=text='2...'{font}:fontcolor=white:fontsize=110:x=(w-text_w)/2:y=790:"
        f"box=1:boxcolor=black@0.55:boxborderw=18:enable='between(t\\,3\\,4)' ,"
        f"drawtext=text='1...'{font}:fontcolor=white:fontsize=110:x=(w-text_w)/2:y=790:"
        f"box=1:boxcolor=black@0.55:boxborderw=18:enable='between(t\\,4\\,5)' ,"
        f"{ring},"
        f"drawtext=text='FOUND IT'{font}:fontcolor=white:fontsize=76:x=(w-text_w)/2:y=1110:"
        f"box=1:boxcolor=red@0.72:boxborderw=18:enable='between(t\\,5\\,7)'"
    )

    alert = _sfx("alert")
    tick = _sfx("tick")
    boom = _sfx("boom")
    audio_inputs = [str(visual)]
    if alert: audio_inputs.append(str(alert))
    if tick: audio_inputs.append(str(tick))
    if boom: audio_inputs.append(str(boom))

    # Input indexes: 0 visual, then alert/tick/boom when present.
    af = [f"sine=frequency=55:sample_rate=44100:duration={total}[bedraw];[bedraw]volume=0.035[bed]"]
    mix_labels = ["[bed]"]
    if alert:
        af.append("[1:a]atrim=0:2,adelay=0|0,volume=0.65[alert]")
        mix_labels.append("[alert]")
    if tick:
        # Three cadence hits from the same tick source, each independently delayed.
        af.append("[2:a]atrim=0:0.35,asplit=3[t2raw][t3raw][t4raw];[t2raw]adelay=2000|2000,volume=0.9[t2];[t3raw]adelay=3000|3000,volume=0.9[t3];[t4raw]adelay=4000|4000,volume=0.9[t4]")
        mix_labels.extend(["[t2]", "[t3]", "[t4]"])
    if boom:
        boom_idx = 3 if alert and tick else (2 if alert or tick else 1)
        af.append(f"[{boom_idx}:a]atrim=0:1.5,adelay=5000|5000,volume=1.35[boom]")
        mix_labels.append("[boom]")
    af.append("".join(mix_labels) + f"amix=inputs={len(mix_labels)}:duration=first:dropout_transition=0[a]")

    cmd = ["ffmpeg", "-y", "-loop", "1", "-i", str(visual)]
    for path in [alert, tick, boom]:
        if path:
            cmd += ["-i", str(path)]
    cmd += [
        "-filter_complex", f"[0:v]{vf}[v];" + ";".join(af),
        "-map", "[v]", "-map", "[a]", "-t", str(total),
        "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(output),
    ]
    _run(cmd)


def render_v20_short(visual_paths: list[Path], spec: dict[str, Any], output_path: Path) -> Path:
    """Render one V20 Short. visual_paths[0] is always frame 0 and contains the hook."""
    if not visual_paths:
        raise ValueError("V20 requires at least one visual")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fmt = spec["format"]
    if fmt == "BRAIN_TRAP":
        if len(visual_paths) != 1:
            raise ValueError("BRAIN_TRAP is single-canvas only: exactly one visual asset is required")
        _render_brain_trap_single_canvas(visual_paths[0], spec, output_path)
        return output_path
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
        if fmt == "MICRO_LOOP" and i == len(cuts) - 2:
            _render_micro_loop(img, dur, clip)
        else:
            _visual_clip(img, dur, clip, modes[i % len(modes)])
        work_clips.append(clip)

    base = WORK_DIR / f"v20_{spec['variant']:03d}_base.mp4"
    _concat(work_clips, base)

    # Frame 0 carries both visual and bold hook. No separate thumbnail is needed.
    font_size = 86 if len(spec["hook_text"]) < 20 else 70
    font_param = get_font_param()
    vf = (
        f"drawtext=text='{hook}'{font_param}:fontcolor=white:fontsize={font_size}:"
        "x=(w-text_w)/2:y=170:box=1:boxcolor=black@0.72:boxborderw=22:"
        "enable='between(t\\,0\\,2.8)'"
    )
    captioned = WORK_DIR / f"v20_{spec['variant']:03d}_captioned.mp4"
    _run(["ffmpeg", "-y", "-i", str(base), "-vf", vf, "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p", "-an", str(captioned)])

    # Native SFX timeline. A subtle synthetic bed starts at frame 0 so the feed never
    # begins with dead air; timed SFX remain the payoff layer.
    sfx_files = []
    for name in spec.get("sfx", []):
        p = _sfx(name)
        if p:
            sfx_files.append(p)
    inputs = [str(captioned)] + [str(p) for p in sfx_files]
    filters = [
        f"sine=frequency=55:sample_rate=44100:duration={total:.3f},volume=0.035,aresample=async=1[bed]"
    ]
    labels = ["[bed]"]
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
