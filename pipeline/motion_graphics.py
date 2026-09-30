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
    w_expr = rf"iw*min(t/{max(duration,0.01):.3f}\,1)"
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
    w_expr = r"min(t/0.25\,1)*8"
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


def mg_pattern_interrupt_hud() -> str:
    """Action HUD: Red warning border + huge 'STOP. 🚨' interrupt stamp."""
    border = f"drawbox=x=0:y=0:w={W}:h={H}:color=0xFF1133@0.65:thickness=14:enable='lte(t,1.4)'"
    stamp = (
        f"drawtext=font='Inter':text='STOP.':fontcolor=white:fontsize=76:"
        f"borderw=8:bordercolor=black@0.95:box=1:boxcolor=0xCC0022@0.92:boxborderw=20|40|20|40:"
        f"x=(w-text_w)/2:y=h*0.28:enable='lte(t,1.6)'"
    )
    return f"{border},{stamp}"


def mg_challenge_hud(payload: str) -> str:
    """Action HUD: Quick test badge + dual comparison pill."""
    clean = (payload or "A  OR  B").replace("'", "").replace(":", "-")
    tag = (
        f"drawtext=font='Inter':text='QUICK TEST':fontcolor=0xFFE600:fontsize=36:"
        f"borderw=4:bordercolor=black@0.9:box=1:boxcolor=black@0.75:boxborderw=12|24|12|24:"
        f"x=(w-text_w)/2:y=h*0.25"
    )
    card = (
        f"drawtext=font='Inter':text='{clean}':fontcolor=white:fontsize=44:"
        f"borderw=5:bordercolor=black@0.95:box=1:boxcolor=0x002B49@0.88:boxborderw=16|32|16|32:"
        f"x=(w-text_w)/2:y=h*0.33"
    )
    return f"{tag},{card}"


def mg_countdown_hud(duration: float) -> str:
    """Action HUD: 3-2-1 center circular countdown."""
    c3 = (
        f"drawtext=font='Inter':text='3':fontcolor=white:fontsize=120:"
        f"borderw=8:bordercolor=black@0.95:box=1:boxcolor=0xCC0022@0.85:boxborderw=30|50|30|50:"
        f"x=(w-text_w)/2:y=(h-text_h)/2-100:enable='lte(t,0.9)'"
    )
    c2 = (
        f"drawtext=font='Inter':text='2':fontcolor=white:fontsize=120:"
        f"borderw=8:bordercolor=black@0.95:box=1:boxcolor=0xFF8800@0.85:boxborderw=30|50|30|50:"
        f"x=(w-text_w)/2:y=(h-text_h)/2-100:enable='between(t,0.9,1.8)'"
    )
    c1 = (
        f"drawtext=font='Inter':text='1':fontcolor=white:fontsize=120:"
        f"borderw=8:bordercolor=black@0.95:box=1:boxcolor=0x00CC44@0.85:boxborderw=30|50|30|50:"
        f"x=(w-text_w)/2:y=(h-text_h)/2-100:enable='gte(t,1.8)'"
    )
    tip = (
        f"drawtext=font='Inter':text='THINK FAST ⏱️':fontcolor=0xFFE600:fontsize=36:"
        f"borderw=4:bordercolor=black@0.9:box=1:boxcolor=black@0.75:boxborderw=10|24|10|24:"
        f"x=(w-text_w)/2:y=(h-text_h)/2+60"
    )
    return f"{c3},{c2},{c1},{tip}"


def mg_reveal_hud(payload: str) -> str:
    """Action HUD: Reveal stamped box showing correct answer and rejection."""
    clean = (payload or "ANSWER REVEALED").replace("'", "").replace(":", "-")
    tag = (
        f"drawtext=font='Inter':text='REVEAL':fontcolor=white:fontsize=38:"
        f"borderw=4:bordercolor=black@0.9:box=1:boxcolor=0x00AA44@0.92:boxborderw=12|28|12|28:"
        f"x=(w-text_w)/2:y=h*0.25"
    )
    ans = (
        f"drawtext=font='Inter':text='{clean}':fontcolor=white:fontsize=46:"
        f"borderw=6:bordercolor=black@0.95:box=1:boxcolor=black@0.80:boxborderw=16|32|16|32:"
        f"x=(w-text_w)/2:y=h*0.33"
    )
    return f"{tag},{ans}"


def mg_mechanism_hud(payload: str) -> str:
    """Action HUD: Formula / visual equation box."""
    clean = (payload or "THE CORE RULE").replace("'", "").replace(":", "-")
    tag = (
        f"drawtext=font='Inter':text='THE MECHANISM':fontcolor=0x00E5FF:fontsize=34:"
        f"borderw=4:bordercolor=black@0.9:box=1:boxcolor=black@0.75:boxborderw=10|24|10|24:"
        f"x=(w-text_w)/2:y=h*0.25"
    )
    formula = (
        f"drawtext=font='Inter':text='{clean}':fontcolor=white:fontsize=42:"
        f"borderw=5:bordercolor=black@0.95:box=1:boxcolor=0x0D1B2A@0.88:boxborderw=16|32|16|32:"
        f"x=(w-text_w)/2:y=h*0.33"
    )
    return f"{tag},{formula}"


def mg_trap_hud(payload: str) -> str:
    """Action HUD: Exam trap warning banner."""
    clean = (payload or "WATCH FOR THIS TRAP").replace("'", "").replace(":", "-")
    banner = (
        f"drawtext=font='Inter':text='EXAM TRAP':fontcolor=0xFFE600:fontsize=38:"
        f"borderw=4:bordercolor=black@0.9:box=1:boxcolor=0x880000@0.90:boxborderw=12|28|12|28:"
        f"x=(w-text_w)/2:y=h*0.25"
    )
    desc = (
        f"drawtext=font='Inter':text='{clean}':fontcolor=white:fontsize=42:"
        f"borderw=5:bordercolor=black@0.95:box=1:boxcolor=black@0.82:boxborderw=16|32|16|32:"
        f"x=(w-text_w)/2:y=h*0.33"
    )
    return f"{banner},{desc}"


def mg_loop_hud(payload: str) -> str:
    """Action HUD: Interactive comment bait."""
    prompt_text = (payload or "Which part was most useful?").replace("'", "").replace(":", "-")
    cta = (
        f"drawtext=font='Inter':text='{prompt_text}':fontcolor=0xFFE600:fontsize=44:"
        f"borderw=6:bordercolor=black@0.95:box=1:boxcolor=0x003366@0.90:boxborderw=18|36|18|36:"
        f"x=(w-text_w)/2:y=h*0.30"
    )
    return cta


def mg_trap_loop_hud(payload: str) -> str:
    """Final V2 beat: exam-trap warning + exact comment question, no generic outro card."""
    clean = (payload or "DID YOU GET IT?").replace("'", "").replace(":", "-")
    banner = (
        f"drawtext=font='Inter':text='EXAM TRAP':fontcolor=0xFFE600:fontsize=38:"
        f"borderw=4:bordercolor=black@0.9:box=1:boxcolor=0x880000@0.92:boxborderw=12|28|12|28:"
        f"x=(w-text_w)/2:y=h*0.23"
    )
    cta = (
        f"drawtext=font='Inter':text='{clean}':fontcolor=white:fontsize=44:"
        f"borderw=6:bordercolor=black@0.95:box=1:boxcolor=0x003366@0.92:boxborderw=18|36|18|36:"
        f"x=(w-text_w)/2:y=h*0.32"
    )
    return f"{banner},{cta}"



def mg_money_drop_hud(payload: str) -> str:
    """Action HUD: Animated money / balance debit badge."""
    clean = (payload or "₹500 DEDUCTED").replace("'", "").replace(":", " - ")
    tag = (
        f"drawtext=font='Inter':text='💸 CHARGE DETECTED':fontcolor=0xFF3355:fontsize=36:"
        f"borderw=4:bordercolor=black@0.9:box=1:boxcolor=black@0.85:boxborderw=10|24|10|24:"
        f"x=(w-text_w)/2:y=h*0.25"
    )
    val = (
        f"drawtext=font='Inter':text='{clean}':fontcolor=0xFFE600:fontsize=52:"
        f"borderw=6:bordercolor=black@0.95:box=1:boxcolor=0x440011@0.92:boxborderw=16|36|16|36:"
        f"x=(w-text_w)/2:y=h*0.32"
    )
    return f"{tag},{val}"


def mg_numbered_step_hud(payload: str) -> str:
    """Action HUD: Bold numbered feature / step card."""
    clean = (payload or "STEP 01").replace("'", "").replace(":", " - ")
    card = (
        f"drawtext=font='Inter':text='{clean}':fontcolor=white:fontsize=46:"
        f"borderw=5:bordercolor=black@0.95:box=1:boxcolor=0x0D1B2A@0.90:boxborderw=16|36|16|36:"
        f"x=(w-text_w)/2:y=h*0.28"
    )
    return card


def mg_warning_freeze_hud(payload: str) -> str:
    """Action HUD: High-curiosity alert banner (universal, not exam-restricted)."""
    clean = (payload or "WHAT YOU DON'T REALIZE").replace("'", "").replace(":", " - ")
    banner = (
        f"drawtext=font='Inter':text='WATCH OUT':fontcolor=0xFFE600:fontsize=38:"
        f"borderw=4:bordercolor=black@0.9:box=1:boxcolor=0x770000@0.90:boxborderw=12|28|12|28:"
        f"x=(w-text_w)/2:y=h*0.25"
    )
    desc = (
        f"drawtext=font='Inter':text='{clean}':fontcolor=white:fontsize=44:"
        f"borderw=5:bordercolor=black@0.95:box=1:boxcolor=black@0.85:boxborderw=16|32|16|32:"
        f"x=(w-text_w)/2:y=h*0.33"
    )
    return f"{banner},{desc}"


def mg_v7_beat_hud(action_type: str, payload: str, accent: str) -> str:
    """Premium teaching overlays for the V7 six-beat script; no game-show UI."""
    clean = (payload or "").replace("'", "").replace(":", " - ").strip()[:90]
    colors = {
        "hook": "0xFFFFFF",
        "context": "0x8FE8FF",
        "mechanism": "0xFFE45B",
        "example": "0x7DFFB2",
        "exam_takeaway": "0xFFB35C",
        "memory_lock": "0xFFFFFF",
    }
    c = colors.get(action_type, "0xFFFFFF")
    if not clean:
        return ""
    if action_type == "hook":
        return (
            f"drawtext=font='Inter':text='{clean}':fontcolor={c}:fontsize=48:borderw=5:bordercolor=black@0.82:"
            "x=54:y=h*0.24"
        )
    if action_type == "context":
        return (
            f"drawtext=font='Inter':text='{clean}':fontcolor={c}:fontsize=34:borderw=3:bordercolor=black@0.75:"
            "x=54:y=h*0.22,drawline=x1=54:y1=h*0.29:x2=420:y2=h*0.29:color=0x8FE8FF@0.65:thickness=5"
        )
    if action_type == "mechanism":
        return (
            "drawtext=font='Inter':text='HOW IT WORKS':fontcolor=0xFFE45B:fontsize=28:borderw=2:bordercolor=black@0.8:x=54:y=h*0.18,"
            f"drawtext=font='Inter':text='{clean}':fontcolor=white:fontsize=40:borderw=4:bordercolor=black@0.85:x=54:y=h*0.25"
        )
    if action_type == "example":
        return (
            "drawtext=font='Inter':text='EXAMPLE':fontcolor=0x7DFFB2:fontsize=28:borderw=2:bordercolor=black@0.8:x=54:y=h*0.18,"
            f"drawtext=font='Inter':text='{clean}':fontcolor=white:fontsize=38:borderw=4:bordercolor=black@0.85:x=54:y=h*0.25"
        )
    if action_type == "exam_takeaway":
        return (
            "drawtext=font='Inter':text='EXAM CLUE':fontcolor=0xFFB35C:fontsize=28:borderw=2:bordercolor=black@0.8:x=54:y=h*0.18,"
            f"drawtext=font='Inter':text='{clean}':fontcolor=white:fontsize=40:borderw=4:bordercolor=black@0.85:x=54:y=h*0.25"
        )
    return (
        "drawtext=font='Inter':text='REMEMBER':fontcolor=0xFFFFFF:fontsize=28:borderw=2:bordercolor=black@0.8:x=54:y=h*0.18,"
        f"drawtext=font='Inter':text='{clean}':fontcolor=white:fontsize=42:borderw=5:bordercolor=black@0.9:x=54:y=h*0.25"
    )


def build_action_hud(action_type: str, payload: str, duration: float, accent: str, allow_text: bool = True) -> str:
    """Return the dedicated Action HUD overlay for this scene's psychological role.

    ``drawtext`` is not available in every GitHub-hosted FFmpeg build.  Keep
    text HUDs opt-in so the renderer can fall back to ASS captions without
    breaking the entire scene.
    """
    if not allow_text:
        return ""
    act = (action_type or "explanation").lower().strip()
    if act in {"hook", "context", "mechanism", "example", "exam_takeaway", "memory_lock"}:
        return mg_v7_beat_hud(act, payload, accent)
    if act == "pattern_interrupt":
        return mg_pattern_interrupt_hud()
    elif act == "challenge":
        return mg_challenge_hud(payload)
    elif act == "countdown":
        return mg_countdown_hud(duration)
    elif act == "reveal":
        return mg_reveal_hud(payload)
    elif act == "mechanism":
        return mg_mechanism_hud(payload)
    elif act in ("trap", "warning"):
        return mg_trap_hud(payload)
    elif act == "loop":
        return mg_loop_hud(payload)
    elif act == "trap_loop":
        return mg_trap_loop_hud(payload)
    return ""


def build_motion_graphics_filter(
    duration: float,
    accent: str,
    scene_index: int = 0,
    total_scenes: int = 1,
    is_hook: bool = False,
    action_type: str = "explanation",
    action_payload: str = "",
    allow_drawtext: bool = False,
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

    # Action HUD layer: dedicated interactive visual device
    action_hud = build_action_hud(action_type, action_payload, duration, accent, allow_text=allow_drawtext)
    if action_hud:
        parts.append(action_hud)

    return ",".join(parts)

def ensure_procedural_sfx(sfx_dir: Path) -> None:
    """Synthesize procedural sound effects if missing via ffmpeg lavfi."""
    sfx_dir.mkdir(parents=True, exist_ok=True)
    cues = {
        "boom.wav": ["-f", "lavfi", "-i", "sine=f=60:b=4:d=0.8,afade=t=out:st=0.1:d=0.7"],
        "tick.wav": ["-f", "lavfi", "-i", "sine=f=1200:d=0.08,afade=t=out:st=0.01:d=0.07"],
        "chime.wav": ["-f", "lavfi", "-i", "sine=f=880:d=0.4,afade=t=out:st=0.05:d=0.35"],
        "whoosh.wav": ["-f", "lavfi", "-i", "anoisesrc=d=0.5:c=pink,lowpass=f=1200,afade=t=in:st=0:d=0.15,afade=t=out:st=0.15:d=0.35"],
        "alert.wav": ["-f", "lavfi", "-i", "sine=f=800:d=0.25,afade=t=out:st=0.05:d=0.20"],
        "cash.wav": ["-f", "lavfi", "-i", "sine=f=1600:d=0.15,afade=t=out:st=0.02:d=0.13"],
    }
    import subprocess
    for fname, args in cues.items():
        dst = sfx_dir / fname
        if not dst.exists():
            try:
                subprocess.run(
                    ["ffmpeg", "-y", *args, "-c:a", "pcm_s16le", str(dst)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────────────────
# Unified runtime motion-graphics renderer.
# IMPORTANT: drawtext is optional because some GitHub Actions FFmpeg builds
# do not expose the filter.  The production default is drawbox + ASS captions.
# ─────────────────────────────────────────────────────────────────────────────
_V6_ROLES = {"hook", "context", "mechanism", "example", "exam_takeaway", "memory_lock", "difference_card"}


def _v8_difference_hud(payload: str, accent: str, allow_drawtext: bool = False) -> str:
    """Final comparison card frame. Artwork stays dominant; text is optional."""
    parts = [
        "drawbox=x=36:y=0:w=iw-72:h=ih*0.70:color=black@0.10:t=3",
    ]
    if allow_drawtext:
        parts.append(
            "drawtext=font='Inter':text='KEY DIFFERENCE':fontcolor=0xFFE45B:fontsize=24:"
            "borderw=2:bordercolor=black@0.76:x=54:y=60"
        )
    return ",".join(parts)


def build_motion_graphics_filter(
    duration: float,
    accent: str,
    scene_index: int = 0,
    total_scenes: int = 1,
    is_hook: bool = False,
    action_type: str = "explanation",
    action_payload: str = "",
    allow_drawtext: bool = False,
) -> str:
    """Build runtime-safe motion graphics.

    The default path intentionally contains NO drawtext.  Word captions are
    burned through ASS/libass in render.py, while drawbox handles non-text
    motion.  drawtext may be enabled explicitly when the installed FFmpeg
    exposes it.
    """
    act = (action_type or "explanation").lower().strip()
    parts: list[str] = [mg_progress_bar(duration, accent)]
    if is_hook:
        parts.append(mg_hook_sweep(accent))

    # Keep the final difference card visually framed without hard-coding text
    # onto the image/video layer.  The artwork itself carries the explanation.
    if act == "difference_card":
        parts.append(_v8_difference_hud(action_payload, accent, allow_drawtext=allow_drawtext))
        return ",".join(p for p in parts if p)

    # Legacy interactive/game HUDs are disabled in the current value-first
    # creative contract.  Only enable text HUDs when explicitly requested.
    if allow_drawtext and act not in _V6_ROLES:
        action_hud = build_action_hud(act, action_payload, duration, accent, allow_text=True)
        if action_hud:
            parts.append(action_hud)
    return ",".join(p for p in parts if p)


def ensure_procedural_sfx(sfx_dir: Path) -> None:
    """Synthesize procedural sound effects if missing via ffmpeg lavfi."""
    sfx_dir.mkdir(parents=True, exist_ok=True)
    cues = {
        "boom.wav": ["-f", "lavfi", "-i", "sine=f=60:b=4:d=0.8,afade=t=out:st=0.1:d=0.7"],
        "tick.wav": ["-f", "lavfi", "-i", "sine=f=1200:d=0.08,afade=t=out:st=0.01:d=0.07"],
        "chime.wav": ["-f", "lavfi", "-i", "sine=f=880:d=0.4,afade=t=out:st=0.05:d=0.35"],
        "whoosh.wav": ["-f", "lavfi", "-i", "anoisesrc=d=0.5:c=pink,lowpass=f=1200,afade=t=in:st=0:d=0.15,afade=t=out:st=0.15:d=0.35"],
        "alert.wav": ["-f", "lavfi", "-i", "sine=f=800:d=0.25,afade=t=out:st=0.05:d=0.20"],
        "cash.wav": ["-f", "lavfi", "-i", "sine=f=1600:d=0.15,afade=t=out:st=0.02:d=0.13"],
    }
    import subprocess
    for fname, args in cues.items():
        dst = sfx_dir / fname
        if not dst.exists():
            try:
                subprocess.run(
                    ["ffmpeg", "-y", *args, "-c:a", "pcm_s16le", str(dst)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            except Exception:
                pass
