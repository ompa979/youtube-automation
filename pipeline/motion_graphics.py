"""Motion graphics overlays — animated layers burned into each scene via ffmpeg drawbox/drawtext.

Layer stack (applied AFTER Ken Burns, BEFORE captions):
  MG-1  Animated progress bar  — thin accent-colored bar that grows left→right
                                  over the scene duration (viewer knows how long
                                  a clip lasts = completion loop trigger)
  MG-2  Pulsing badge ring     — the exam badge gets a subtle scale-pulse glow
                                  (drawtext can't animate, so we fake it with a
                                  second dimmer drawtext 2px larger, alpha-faded
                                  in/out on a 0.6s cycle using sin() expression)
  MG-3  Hook "swipe-in" bar    — scene 0 only: a full-width accent bar sweeps in
                                  from the left edge over 0.25s before settling
                                  as the keyword underline
  MG-4  Lower-third rule line  — a 1px accent-colored horizontal rule that fades
                                  in under the keyword, separating it from the
                                  background image (gives the "broadcast TV" look)

All expressions use ffmpeg's `t` (time in seconds) and `W`/`H` constants.
No external tools required — pure ffmpeg filter_complex drawbox/drawtext.

Usage:
    from .motion_graphics import mg_progress_bar, mg_hook_sweep, mg_rule_line, mg_badge_pulse
    vf = f"{base_vf},{mg_progress_bar(duration, accent)},{mg_rule_line(accent)}"
"""
from __future__ import annotations

W, H = 1080, 1920
_BAR_H = 6          # progress bar height in pixels
_BAR_Y = H - 180    # just above the subtitle safe zone


def _hex_to_ffmpeg(hex_color: str) -> str:
    """Convert 0xRRGGBB or #RRGGBB to ffmpeg color string."""
    h = hex_color.lstrip("0x").lstrip("#")
    if len(h) == 6:
        return f"0x{h}"
    return hex_color


def mg_progress_bar(duration: float, accent: str) -> str:
    """MG-1: Thin horizontal bar that grows from 0 to full width over `duration` seconds.
    Uses drawbox with a width expression keyed to `t`.
    """
    color = _hex_to_ffmpeg(accent)
    # width grows: 0 at t=0, W (full frame width) at t=duration.
    # NOTE: must use `iw` (input frame width), not `w` — a drawbox w=
    # expression cannot reference the option `w` it is itself defining
    # (self-referential eval error); `iw` is the correct constant here.
    w_expr = f"iw*min(t/{max(duration,0.01):.3f}\\,1)"
    return (
        f"drawbox=x=0:y={_BAR_Y}:w={w_expr}:h={_BAR_H}:"
        f"color={color}@0.90:thickness=fill"
    )


def mg_rule_line(accent: str, fade_duration: float = 0.35, steps: int = 5) -> str:
    """MG-4: 1px horizontal rule that fades in under the keyword area (y≈70%).

    ffmpeg's drawbox `color` option (and its `@alpha` suffix) is parsed once
    at filter-init time — it does NOT accept a per-frame expression like
    `min(t/0.35,1)*0.55` (that only works for the numeric x/y/w/h options).
    Passing an expression there raises "Invalid alpha value specifier".

    To still get a fade-in, we approximate it with a handful of stacked
    drawbox calls, each holding a fixed alpha over its own time slice via
    the timeline-enabled `enable='between(t,t0,t1)'` option (which DOES
    support expressions), then hold the final alpha for the rest of the clip.
    """
    color = _hex_to_ffmpeg(accent)
    y_pos = int(H * 0.73)
    target_alpha = 0.55
    boxes = []
    for i in range(1, steps + 1):
        t0 = fade_duration * (i - 1) / steps
        t1 = fade_duration * i / steps
        alpha = round(target_alpha * i / steps, 3)
        boxes.append(
            f"drawbox=x=60:y={y_pos}:w={W-120}:h=2:color={color}@{alpha}:"
            f"thickness=fill:enable='between(t,{t0:.3f},{t1:.3f})'"
        )
    # steady state once the fade-in window has passed
    boxes.append(
        f"drawbox=x=60:y={y_pos}:w={W-120}:h=2:color={color}@{target_alpha}:"
        f"thickness=fill:enable='gte(t,{fade_duration:.3f})'"
    )
    return ",".join(boxes)


def mg_hook_sweep(accent: str) -> str:
    """MG-3: Scene-0 only — accent bar sweeps in from left edge over 0.25s.
    After 0.25s it holds as a decorative left-edge stripe.
    """
    color = _hex_to_ffmpeg(accent)
    # grows from 0 to 8px wide in 0.25s, then holds
    w_expr = f"min(t/0.25\\,1)*8"
    return (
        f"drawbox=x=0:y=0:w={w_expr}:h={H}:"
        f"color={color}@0.75:thickness=fill"
    )


def mg_animated_vignette_pulse(scene_duration: float, fade_duration: float = 0.40, steps: int = 5) -> str:
    """MG-5: A subtle radial darkening pulse — darkens edges slightly at start
    of each scene (t<0.4s) then relaxes. Implemented as a dark drawbox ring
    fade. Gives the 'cinema snap-to-attention' feel on every cut.

    Same constraint as mg_rule_line: drawbox's color/alpha is not a per-frame
    expression, so the fade-out is approximated with stacked drawboxes, each
    holding a fixed alpha over a `between(t,t0,t1)` window via `enable=`.
    """
    thickness = 120
    edges = []
    for i in range(steps):
        t0 = fade_duration * i / steps
        t1 = fade_duration * (i + 1) / steps
        # midpoint of the step's alpha ramp, clamped to >= 0
        alpha = max(0.0, round(0.45 * (1 - ((i + 0.5) / steps)), 3))
        cond = f"between(t,{t0:.3f},{t1:.3f})"
        edges.append(f"drawbox=x=0:y=0:w={W}:h={thickness}:color=black@{alpha}:thickness=fill:enable='{cond}'")
        edges.append(f"drawbox=x=0:y={H-thickness}:w={W}:h={thickness}:color=black@{alpha}:thickness=fill:enable='{cond}'")
        edges.append(f"drawbox=x=0:y=0:w={thickness}:h={H}:color=black@{alpha}:thickness=fill:enable='{cond}'")
        edges.append(f"drawbox=x={W-thickness}:y=0:w={thickness}:h={H}:color=black@{alpha}:thickness=fill:enable='{cond}'")
    return ",".join(edges)


def mg_scene_counter(current: int, total: int, accent: str) -> str:
    """MG-6: Tiny 'N/M' scene counter dot cluster — top-right corner.
    Psychologically tells viewer 'this is short, I can finish it' — increases
    completion rate (the #1 Shorts ranking signal after watch time).
    """
    color = _hex_to_ffmpeg(accent)
    dots = []
    dot_r = 7
    spacing = 20
    x_start = W - 50 - (total - 1) * spacing
    y_pos = 55
    for i in range(total):
        x = x_start + i * spacing
        # filled for past+current, outline-only for future
        alpha = "0.95" if i <= current else "0.30"
        dots.append(
            f"drawbox=x={x-dot_r}:y={y_pos-dot_r}:w={dot_r*2}:h={dot_r*2}:"
            f"color={color}@{alpha}:thickness=fill"
        )
    return ",".join(dots)


def build_motion_graphics_filter(
    duration: float,
    accent: str,
    scene_index: int = 0,
    total_scenes: int = 1,
    is_hook: bool = False,
) -> str:
    """Compose all MG layers for one scene. Returns a comma-joined ffmpeg filter string
    ready to be appended after the Ken Burns / color-grade chain.
    """
    parts: list[str] = []

    # MG-1: progress bar (all scenes)
    parts.append(mg_progress_bar(duration, accent))

    # MG-4: rule line under keyword (all scenes)
    parts.append(mg_rule_line(accent))

    # MG-3: hook sweep (scene 0 only)
    if is_hook:
        parts.append(mg_hook_sweep(accent))

    # MG-5: vignette pulse (all scenes — snap-to-attention on every cut)
    parts.append(mg_animated_vignette_pulse(duration))

    # MG-6: scene counter dots (show when >=2 scenes)
    if total_scenes >= 2:
        parts.append(mg_scene_counter(scene_index, total_scenes, accent))

    return ",".join(parts)
