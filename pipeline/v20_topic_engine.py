"""V20 feed-native 40-video creative seed.

No syllabus, no LLM narrative, no SEO topic selection.  The seed is deterministic:
10 Brain Traps + 10 Optical Illusions + 10 Satisfying/Destruction + 10 Micro-Loops.
"""
from __future__ import annotations

from typing import Any

V20_SEED = [
    # 10 BRAIN_TRAP
    ("BRAIN_TRAP", "spot_odd_one", "DON'T BLINK 👁️", "ONE SINGLE CONTINUOUS SCENE for the entire video: a dense field of near-identical glossy black marbles on a dark purple surface, with exactly ONE tiny anomalous eye embedded in a marble in the UPPER-RIGHT quadrant at approximately x=72% and y=43%. The geometric CENTER of the composition must contain only ordinary marbles and NO eye, face, bright anomaly, or dominant object. Keep the anomalous eye small enough to be genuinely difficult to notice at frame zero but structurally visible when the camera later punches toward its coordinate. The odd eye must be physically present in the same base scene from frame one and must never require a scene change.", ["same single marble field for entire video", "exactly one hidden eye at center-right x=65% y=50%", "high contrast black purple background"]),
    ("BRAIN_TRAP", "impossible_count", "HOW MANY?", "A fast-moving field of colorful geometric dots with one hidden duplicate shape; crisp centered composition.", ["colorful geometric dots", "hidden duplicate shape", "rapid visual motion"]),
    ("BRAIN_TRAP", "optical_illusion", "LOOK AT THE CENTER", "A high-contrast spiral optical illusion with a bright center and concentric motion lines, visually stable but hypnotic.", ["black white spiral", "bright center", "hypnotic concentric lines"]),
    ("BRAIN_TRAP", "afterimage_test", "DON'T LOOK AWAY", "A saturated neon shape centered on a dark field, designed for a clean afterimage effect.", ["neon cyan triangle", "deep black background", "strong complementary contrast"]),
    ("BRAIN_TRAP", "find_symbol", "SPOT THE 8", "A wall of nearly identical digits with one clearly shaped 8 hidden among 3s, dense and visually challenging.", ["dense number grid", "one hidden 8", "sharp typography-like symbols"]),
    ("BRAIN_TRAP", "cafe_wall", "IS IT MOVING?", "Offset black and white brick rows that create a classic café-wall style illusion.", ["offset brick rows", "black white tiles", "strong horizontal lines"]),
    ("BRAIN_TRAP", "muller_lyer", "WHICH IS LONGER?", "Two apparently unequal arrow-ended lines aligned vertically in a clean optical illusion composition.", ["two horizontal lines", "opposing arrowheads", "minimal black white design"]),
    ("BRAIN_TRAP", "troxler", "WATCH THE DOT", "A single bright dot surrounded by a soft rotating ring of colored dots, centered and uncluttered.", ["bright center dot", "ring of colored dots", "dark background"]),
    ("BRAIN_TRAP", "odd_emoji", "FIND THE ODD ONE", "A grid of near-identical expressive emoji faces with one subtly different face in the center-safe area.", ["emoji face grid", "one subtle mismatch", "bright clean background"]),
    ("BRAIN_TRAP", "duck_rabbit", "WHAT DO YOU SEE?", "A clean reversible duck-rabbit style silhouette with ambiguous contours and strong contrast.", ["ambiguous black silhouette", "duck profile", "rabbit profile"]),
    # 10 OPTICAL_ILLUSION
    ("OPTICAL_ILLUSION", "hermann_grid", "WHERE DID IT GO?", "A crisp Hermann grid of white intersections on a dark field with a subtle perceptual illusion.", ["black grid", "white intersections", "high contrast"]),
    ("OPTICAL_ILLUSION", "rotating_snakes", "THEY ARE MOVING", "A high-detail rotating-snakes style pattern that appears to move while the image itself is static.", ["spiral snake rings", "vivid alternating colors", "dense pattern"]),
    ("OPTICAL_ILLUSION", "checker_shadow", "SAME COLOR?", "A checkerboard with a dramatic cast shadow creating a famous color-perception illusion.", ["checkerboard", "cast shadow", "two matching squares"]),
    ("OPTICAL_ILLUSION", "impossible_stairs", "WHICH WAY?", "A clean impossible staircase geometry with a seamless perspective contradiction.", ["impossible staircase", "white geometry", "deep perspective"]),
    ("OPTICAL_ILLUSION", "penrose_triangle", "THIS CAN'T EXIST", "A photorealistic Penrose triangle sculpture with impossible connected corners.", ["metal Penrose triangle", "studio lighting", "impossible geometry"]),
    ("OPTICAL_ILLUSION", "spiral_motion", "IS IT SPINNING?", "A monochrome radial spiral that creates a powerful apparent motion effect.", ["radial spiral", "black white", "center focal point"]),
    ("OPTICAL_ILLUSION", "size_contrast", "WHICH IS BIGGER?", "Two identical circles surrounded by differently sized circles, creating a strong size illusion.", ["two identical circles", "surrounding circles", "clean white background"]),
    ("OPTICAL_ILLUSION", "bent_lines", "THEY LOOK BENT", "Perfectly straight parallel lines crossing a curved visual field and appearing warped.", ["straight parallel lines", "curved field", "minimal geometry"]),
    ("OPTICAL_ILLUSION", "ambiguous_face", "FACE OR FLOWER?", "An ambiguous symmetrical image that flips between a face-like silhouette and a flower-like pattern.", ["symmetrical silhouette", "face profile", "flower pattern"]),
    ("OPTICAL_ILLUSION", "floating_cube", "IS IT FLAT?", "A glowing wireframe cube whose perspective makes it impossible to tell which face is in front.", ["wireframe cube", "glowing edges", "ambiguous perspective"]),
    # 10 SATISFYING / DESTRUCTION
    ("SATISFYING", "hydraulic_press", "WAIT FOR IT...", "A massive hydraulic press is already descending onto a colorful stack of soft rubber balls, extreme close-up.", ["hydraulic press", "soft rubber balls", "metal reflections"]),
    ("SATISFYING", "precision_cut", "PERFECT CUT", "A razor-sharp blade slicing a translucent block of kinetic sand with a perfectly smooth face.", ["precision blade", "kinetic sand block", "clean sliced surface"]),
    ("SATISFYING", "laser_clean", "WATCH IT VANISH", "A bright industrial laser cleaning rust from a dark metal surface, revealing pristine steel beneath.", ["industrial laser", "rusty metal", "clean steel reveal"]),
    ("SATISFYING", "liquid_morph", "SO SMOOTH", "A glossy blob of metallic liquid morphing perfectly through a geometric channel, macro photography.", ["metallic liquid", "geometric channel", "macro detail"]),
    ("SATISFYING", "glass_crush", "CRACK PERFECTLY", "A clear glass prism under controlled pressure beginning to fracture into elegant radial cracks.", ["clear glass prism", "pressure point", "radial cracks"]),
    ("SATISFYING", "slime_press", "TOO PERFECT", "A glossy neon slime sphere compressed under a transparent press, bulging symmetrically.", ["neon slime", "transparent press", "symmetrical compression"]),
    ("SATISFYING", "honeycomb_slice", "ONE CLEAN SLICE", "A knife making a perfect diagonal slice through a golden honeycomb with sticky texture visible.", ["golden honeycomb", "sharp knife", "sticky honey texture"]),
    ("SATISFYING", "foam_cut", "CLEANEST SLICE", "A hot wire slicing through a dense block of colorful foam in one continuous perfect cut.", ["hot wire", "colorful foam", "smooth cut"]),
    ("SATISFYING", "memory_foam", "WATCH THE RESET", "A heavy metal ball compresses memory foam and the material begins returning to perfect form.", ["metal ball", "memory foam", "slow rebound"]),
    ("SATISFYING", "wax_melt", "MELTS PERFECTLY", "A heated metal edge gliding through layered colorful wax, producing a perfectly smooth channel.", ["heated metal edge", "layered wax", "smooth melted channel"]),
    # 10 MICRO_LOOP
    ("MICRO_LOOP", "infinite_physics", "WAIT HOW?", "A polished marble rolls through a circular track and appears to pass seamlessly back into its starting point.", ["polished marble", "circular track", "seamless reset"]),
    ("MICRO_LOOP", "droste_effect", "LOOK CLOSELY", "A picture frame contains the same frame recursively, creating a clean infinite visual tunnel.", ["ornate picture frame", "recursive frame", "infinite tunnel"]),
    ("MICRO_LOOP", "geometric_transformation", "IT RESET", "A bright cube smoothly unfolds into a flat square and reforms into the same cube with a perfect loop point.", ["glowing cube", "flat square", "perfect transformation"]),
    ("MICRO_LOOP", "domino_wave", "NEVER STOPS", "A circular chain of glossy dominoes falls and reconnects visually to the first domino.", ["circular domino chain", "falling wave", "perfect loop"]),
    ("MICRO_LOOP", "pendulum", "WHY DOES IT DO THAT?", "A kinetic pendulum sequence swings through an impossible-looking synchronized pattern and resets exactly.", ["metal pendulums", "synchronized motion", "dark studio"]),
    ("MICRO_LOOP", "coffee_pour", "PERFECT LOOP", "A seamless ribbon of coffee pours into a cup while the stream visually reconnects to its beginning.", ["coffee stream", "ceramic cup", "seamless pour"]),
    ("MICRO_LOOP", "slinky", "WATCH THE RESET", "A slinky descends a small step and visually snaps back to its original shape in a seamless loop.", ["metal slinky", "small staircase", "spring reset"]),
    ("MICRO_LOOP", "droplet_collision", "DID IT REWIND?", "Two water droplets collide in macro slow-motion and reform into two droplets at the loop boundary.", ["two water droplets", "macro collision", "black studio"]),
    ("MICRO_LOOP", "zero_friction", "IT NEVER STOPS", "A chrome ball rolls around a perfectly smooth circular bowl with an impossible-looking endless path.", ["chrome ball", "smooth circular bowl", "endless motion"]),
    ("MICRO_LOOP", "screen_shatter", "IT FIXED ITSELF", "A glass-like digital panel shatters outward and instantly reconstructs into an untouched panel.", ["glass digital panel", "shattering fragments", "instant reconstruction"]),
]



# Every V20 subtype gets an explicit FLUX recipe derived from its seed concept.
# The prompt is deliberately visual-first: no educational framing, no text rendered
# into the image, and a strong subject in the 9:16 center-safe region.
_FLUX_STYLE = {
    "BRAIN_TRAP": "photorealistic macro detail, extreme contrast, crisp focal subject, dark cinematic background, immediate visual anomaly, one continuous fixed scene, no alternate scenes, no collage, no slideshow, no camera cut",
    "OPTICAL_ILLUSION": "hypnotic geometric precision, mathematically clean symmetry, high contrast, impossible depth, crisp edges",
    "SATISFYING": "extreme macro photography, tactile materials, dramatic studio lighting, visible mechanical action, ultra-detailed",
    "MICRO_LOOP": "surreal physics visualization, polished materials, precise geometry, cinematic studio lighting, seamless motion cue"
}

FLUX_PROMPT_TEMPLATES: dict[str, str] = {
    subtype: (
        f"{visual_prompt} { _FLUX_STYLE[fmt] }. "
        "Vertical 9:16 composition, hero subject large in frame, action already underway at frame zero, "
        "center-safe composition, no text, no letters, no watermark, no logo, high visual clarity."
    )
    for fmt, subtype, _hook, visual_prompt, _parts in V20_SEED
}

PROFILES: dict[str, dict[str, Any]] = {
    "BRAIN_TRAP": {"duration": 8.0, "timeline": {"hook": 0.0, "tension": 2.0, "reveal": 4.5, "payoff": 6.5, "loop": 8.0}, "sfx": ["tick", "alert", "boom"]},
    "OPTICAL_ILLUSION": {"duration": 8.0, "timeline": {"hook": 0.0, "build": 2.0, "peak": 5.0, "reset": 8.0}, "sfx": ["tick", "alert", "whoosh"]},
    "SATISFYING": {"duration": 7.0, "timeline": {"action": 0.0, "tension": 1.5, "impact": 4.0, "aftermath": 5.5, "loop": 7.0}, "sfx": ["whoosh", "boom", "chime"]},
    "MICRO_LOOP": {"duration": 7.0, "timeline": {"action": 0.0, "escalation": 2.0, "impossible": 5.5, "reset": 7.0}, "sfx": ["whoosh", "alert"]},
}

# Interactive choices are intentionally deferred from the first seed according to the
# locked 10/10/10/10 sprint. The architecture still accepts the format later.
PROFILES["INTERACTIVE_CHOICE"] = {"duration": 8.0, "timeline": {"hook": 0.0, "choices": 2.5, "lock": 5.0, "consequence": 7.0}, "sfx": ["tick", "chime"]}


def generate_v20_spec(video_index: int) -> dict[str, Any]:
    if video_index < 1:
        raise ValueError("video_index must be >= 1")
    seed_index = (video_index - 1) % len(V20_SEED)
    fmt, subtype, hook, visual_prompt, visual_parts = V20_SEED[seed_index]
    profile = PROFILES[fmt]
    visual_prompt = FLUX_PROMPT_TEMPLATES[subtype]
    variant = seed_index + 1
    tracking_tag = f"V20-{fmt}-{subtype.upper()}-{variant:03d}"
    reveal_strategy = "PUNCH_ZOOM_TARGET" if (fmt == "BRAIN_TRAP" and subtype == "spot_odd_one") else ("FULL_FRAME_PULSE" if fmt == "BRAIN_TRAP" else "NONE")
    target = {"x": 0.72, "y": 0.43} if reveal_strategy == "PUNCH_ZOOM_TARGET" else None
    return {
        "seed_index": seed_index,
        "tracking_tag": tracking_tag,
        "format": fmt,
        "subtype": subtype,
        "variant": variant,
        "duration_seconds": profile["duration"],
        "timings": profile["timeline"],
        "sfx": profile["sfx"],
        "hook_text": hook,
        "visual_prompt": visual_prompt,
        "visual_parts": visual_parts,
        "distribution_goal": "SHORTS_FEED",
        "search_intent": False,
        "loop_frame_match": True,
        "title": hook.replace(" 👁️", "").replace(" 💥", "").replace(" 🔁", ""),
        "description": "#shorts",
        "tags": ["shorts"],
        "stock_video_query": f"{subtype.replace('_', ' ')} macro satisfying destruction action" if fmt == "SATISFYING" else None,
        "source_contract": "REAL_MOTION_VIDEO" if fmt == "SATISFYING" else "SINGLE_CANVAS",
        "reveal_strategy": reveal_strategy,
        "target_point": target,
    }
