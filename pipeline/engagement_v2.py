"""Deterministic packaging + interaction helpers for ExamCracker Shorts V2.

The LLM may suggest the creative direction, but these rules are enforced after
LLM generation so the production renderer cannot silently regress into a
passive "AI background + captions" Short.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

from .thumbnail_ai import cloudflare_configured, generate_background

if TYPE_CHECKING:
    from .script_gen import Script

# The renderer understands these exact beats. Keeping this centralized avoids
# drift between prompt, QA and render layers.
V2_ACTION_SEQUENCE = (
    "pattern_interrupt",
    "challenge",
    "countdown",
    "reveal",
    "mechanism",
    "trap_loop",
)

_EXAM_RE = re.compile(
    r"\b(IBPS\s*(?:SO(?:\s*IT)?|PO|Clerk|RRB)|SBI\s*(?:PO|Clerk|SO)|"
    r"RBI\s*(?:Grade\s*B|Assistant)|NABARD|SEBI|GATE|UPSC|SSC)\b",
    re.I,
)

_GENERIC_TITLE_WORDS = {
    "explained", "difference", "easy", "simple", "quick", "guide",
    "trick", "trap", "method", "the", "a", "an", "for", "in", "of",
    "asked", "always", "tests", "test", "exam", "exams", "seconds",
    "second", "minute", "minutes", "that", "this", "you", "your",
}


def _clean_text(value: str) -> str:
    return " ".join((value or "").replace("\n", " ").split()).strip()


def _question_from_challenge(script: "Script") -> str:
    """Extract a compact, truthful challenge question from scene 1."""
    if not getattr(script, "scenes", None) or len(script.scenes) < 2:
        return "Can You Get It Right?"
    scene = script.scenes[1]
    payload = _clean_text(getattr(scene, "action_payload", ""))
    narration = _clean_text(getattr(scene, "narration", ""))

    # Prefer an A/B payload because it makes a strong thumbnail.
    ab = re.search(
        r"A\s*[\)\:\-]\s*([^|]+?)\s*(?:\||vs\.?|versus)\s*B\s*[\)\:\-]\s*(.+)$",
        payload,
        re.I,
    )
    if ab:
        a = _clean_text(ab.group(1)).rstrip("?.!")
        b = _clean_text(ab.group(2)).rstrip("?.!")
        return f"{a} OR {b}?"

    for source in (payload, narration):
        if not source:
            continue
        # First sentence/question, capped for thumbnail readability.
        q = re.split(r"(?<=[?!])\s+", source)[0].strip()
        if "?" in q:
            q = q[:90].strip()
            return q
        low = q.lower()
        if any(low.startswith(w) for w in ("which ", "where ", "why ", "how ", "can you ", "what ", "who ")):
            return (q.rstrip(".!?") + "?")[:90]

    if narration:
        q = narration[:72].rstrip(".,;: ")
        return q + "?"
    return "Can You Get It Right?"


def _detailed_question_from_challenge(script: "Script") -> str:
    """Prefer the actual spoken question for titles; fall back to the compact A/B cue."""
    if not getattr(script, "scenes", None) or len(script.scenes) < 2:
        return ""
    narration = _clean_text(getattr(script.scenes[1], "narration", ""))
    if "?" in narration:
        q = re.split(r"(?<=[?!])\s+", narration)[0].strip()
        if len(q) <= 78:
            return q
    return _question_from_challenge(script)


def _exam_label(topic: str, title: str) -> str:
    for text in (topic, title):
        m = _EXAM_RE.search(text or "")
        if m:
            return re.sub(r"\s+", " ", m.group(1)).strip()
    return "EXAMCRACKER AI"


def _concept_from_topic(topic: str, base_title: str = "") -> str:
    text = _clean_text(topic)
    # The part before the first colon is usually the cleanest concept label.
    if ":" in text:
        text = text.split(":", 1)[0].strip()
    elif " — " in text:
        text = text.split(" — ", 1)[0].strip()
    if not text:
        text = _clean_text(base_title)
    # Remove a leading exam prefix from the concept card.
    text = re.sub(r"^(?:IBPS|SBI|RBI|UPSC|SSC|GATE)[^:|\-–—]*[:|\-–—]\s*", "", text, flags=re.I)
    return text[:54].rstrip(" :-,|–—")


def build_click_title(topic: str, base_title: str, script: "Script") -> str:
    """Build a curiosity-first title while preserving the actual concept and exam."""
    question = _detailed_question_from_challenge(script)
    concept = _concept_from_topic(topic, base_title)
    exam = _exam_label(topic, base_title)

    q = _clean_text(question).rstrip(".!?")
    # If the question is basically a generic CTA, keep the SEO title's concept.
    generic_q = q.lower() in {"can you get it right", "can you solve this", "what do you think"}

    if not generic_q and q:
        if concept and not all(word.lower() in q.lower() for word in concept.split() if len(word) > 3) and len(concept) <= 42:
            candidate = f"{concept}: {q}?"
        else:
            candidate = f"{q}?"
    else:
        candidate = _clean_text(base_title)

    # Add exam identity only when it fits. Search intent remains in the concept.
    if exam and exam.lower() not in candidate.lower():
        suffix = f" | {exam}"
        if len(candidate) + len(suffix) <= 85:
            candidate += suffix
        else:
            shortened = candidate[: 85 - len(suffix) - 1].rsplit(" ", 1)[0]
            candidate = f"{shortened}{suffix}"

    candidate = re.sub(r"\s+", " ", candidate).strip(" -:|")
    candidate = candidate[:85].rstrip(" -:|,;")
    return candidate or _clean_text(base_title)[:85]


def build_thumbnail_text(script: "Script") -> str:
    """Short, high-contrast question for a 16:9 thumbnail."""
    q = _question_from_challenge(script)
    q = re.sub(r"\s+", " ", q).strip()
    # Avoid punctuation overload in the thumbnail while retaining the question mark.
    q = q.replace("❓", "?")
    if len(q) > 52:
        q = q[:52].rsplit(" ", 1)[0].rstrip(".,;:") + "?"
    return q.upper()


def enforce_v2_contract(script: "Script") -> None:
    """Normalize generated scenes to the six render-time psychological roles."""
    if not script.scenes:
        return

    # Keep 6 scenes as the target; QA will reject fewer/more, so this function
    # only normalizes role metadata and does not fabricate narration.
    for i, scene in enumerate(script.scenes[:6]):
        role = V2_ACTION_SEQUENCE[i] if i < len(V2_ACTION_SEQUENCE) else V2_ACTION_SEQUENCE[-1]
        scene.action_type = role

        if role == "pattern_interrupt":
            scene.on_screen_text = "STOP 🚨"
            scene.action_payload = "STOP. 🚨"
        elif role == "challenge":
            if not _clean_text(scene.action_payload):
                scene.action_payload = _clean_text(scene.on_screen_text) or "A OR B?"
            scene.on_screen_text = "A OR B?"
        elif role == "countdown":
            scene.action_payload = "3... 2... 1..."
            scene.on_screen_text = "THINK FAST"
        elif role == "reveal":
            if not _clean_text(scene.action_payload):
                anchor = _clean_text(scene.card_points[0]) if getattr(scene, "card_points", None) else "ANSWER REVEALED"
                scene.action_payload = anchor
            scene.on_screen_text = "REVEAL"
        elif role == "mechanism":
            if not _clean_text(scene.action_payload):
                anchor = _clean_text(scene.card_points[0]) if getattr(scene, "card_points", None) else "THE CORE RULE"
                scene.action_payload = anchor
            scene.on_screen_text = "THE TRICK"
        elif role == "trap_loop":
            if not _clean_text(scene.action_payload):
                scene.action_payload = _question_from_challenge(script)
            scene.on_screen_text = "DID YOU GET IT?"

    if len(script.scenes) >= 2:
        script.thumbnail_text = build_thumbnail_text(script)
    else:
        script.thumbnail_text = "CAN YOU GET IT RIGHT?"


def build_comment_cta(script: "Script") -> str:
    question = _question_from_challenge(script)
    return f"{question} Comment below."


def _font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def _wrap_words(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else current + " " + word
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines[:4]


def _extract_frame_16x9(video_path: Path, out_path: Path, at_sec: float) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-ss", f"{max(0.0, at_sec):.3f}", "-i", str(video_path),
        "-frames:v", "1", "-vf", "scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720",
        "-q:v", "2", str(out_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not out_path.exists():
        raise RuntimeError(f"thumbnail frame extraction failed: {proc.stderr[-1200:]}")


THUMBNAIL_W = 1280
THUMBNAIL_H = 720
THUMBNAIL_VARIANTS = max(1, int(os.getenv("THUMBNAIL_VARIANTS", "3")))

# 10 reusable thumbnail archetypes. The background is AI-generated when an
# endpoint is configured; Pillow owns all final typography/layout so the copy
# remains crisp and deterministic across hundreds of automated thumbnails.
THUMBNAIL_ARCHETYPES = (
    "question",
    "trap",
    "countdown",
    "compare",
    "mystery",
    "number",
    "output",
    "true_false",
    "boss_fight",
    "formula",
)


def _thumbnail_archetype(topic: str, question: str, index: int = 0) -> str:
    text = f"{topic} {question}".lower()
    if re.search(r"\b(vs\.?|versus|difference|compare)\b", text):
        preferred = ["compare", "trap", "question"]
    elif re.search(r"\b(trap|wrong|mistake|pitfall|confuse|confusion)\b", text):
        preferred = ["trap", "question", "boss_fight"]
    elif re.search(r"\b(output|code|query|program|machine)\b", text):
        preferred = ["output", "countdown", "question"]
    elif re.search(r"\b(how many|digits|number|value|percent|percentage)\b", text):
        preferred = ["number", "countdown", "question"]
    elif re.search(r"\b(formula|equation|calculate|calculation|simplification)\b", text):
        preferred = ["formula", "countdown", "question"]
    elif re.search(r"\b(true|false|correct|incorrect)\b", text):
        preferred = ["true_false", "trap", "question"]
    elif re.search(r"\b(boss\s*fight|challenge\s*level|level\s*\d+|boss)\b", text):
        preferred = ["boss_fight", "question", "mystery"]
    elif re.search(r"\b(why|how|secret|reason|actually)\b", text):
        preferred = ["mystery", "question", "trap"]
    else:
        preferred = ["question", "boss_fight", "mystery"]
    return preferred[index % len(preferred)]


def _thumbnail_visual_prompt(topic: str, question: str, archetype: str, seed: int) -> str:
    # Keep the generated art text-free. The local compositor renders the exact
    # headline so OCR/readability is not left to the diffusion model.
    role = {
        "question": "a dramatic split-screen choice with two clearly distinct hero objects",
        "trap": "a high-stakes exam trap scene with one object circled and another crossed out",
        "countdown": "a tense countdown scene with a large glowing timer-like visual cue and an object under pressure",
        "compare": "two contrasting hero objects facing each other with a strong visual divide",
        "mystery": "a mysterious reveal scene with one hidden/partially obscured hero object and a dramatic light beam",
        "number": "one dominant numerical concept represented visually with a single unmistakable hero object",
        "output": "a coding/output challenge with code-like abstract blocks, arrows and a clear final object/result",
        "true_false": "a dramatic split between a green confirmation state and a red rejection state",
        "boss_fight": "a high-energy exam boss-fight scene with a glowing challenge panel and one dominant concept object",
        "formula": "a visually constructed equation or process using luminous blocks, arrows and one dominant result object",
    }[archetype]
    return (
        f"Create a premium YouTube thumbnail background for an Indian competitive-exam education video. "
        f"Topic: {topic}. Viewer question: {question}. Visual direction: {role}. "
        f"16:9 landscape composition, cinematic dark background, high contrast, vivid electric cyan + warm yellow + red accents, "
        f"photorealistic or premium 3D infographic aesthetic, one dominant hero subject, dramatic rim light, deep depth, "
        f"clean negative space for typography, mobile-feed readability, no logos, no watermarks, no letters, no numbers, no written words. "
        f"Seed concept {seed}."
    )


def _request_ai_background(prompt: str, seed: int) -> Image.Image | None:
    """Generate a clean AI hero background via the configured provider(s)."""
    image, provider = generate_background(prompt, seed)
    if image is not None:
        print(f"[thumbnail] AI background provider={provider} seed={seed}")
    return image


def _fit_background(img: Image.Image) -> Image.Image:
    img = img.convert("RGB")
    target_ratio = THUMBNAIL_W / THUMBNAIL_H
    current_ratio = img.width / img.height if img.height else target_ratio
    if current_ratio > target_ratio:
        new_w = int(img.height * target_ratio)
        left = max((img.width - new_w) // 2, 0)
        img = img.crop((left, 0, left + new_w, img.height))
    else:
        new_h = int(img.width / target_ratio)
        top = max((img.height - new_h) // 2, 0)
        img = img.crop((0, top, img.width, top + new_h))
    return img.resize((THUMBNAIL_W, THUMBNAIL_H), Image.Resampling.LANCZOS)


def _load_clean_background(video_path: Path, background_path: Path | None, challenge_time: float) -> Image.Image:
    if background_path and background_path.exists():
        return _fit_background(Image.open(background_path))
    frame_path = video_path.parent / "_thumb_bg.jpg"
    _extract_frame_16x9(video_path, frame_path, challenge_time)
    try:
        return _fit_background(Image.open(frame_path))
    finally:
        frame_path.unlink(missing_ok=True)


def _rounded_box(draw: ImageDraw.ImageDraw, box, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def _draw_arrow(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int], fill, width=16):
    draw.line([start, end], fill=fill, width=width)
    import math
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    size = 28
    a1 = angle + 2.55
    a2 = angle - 2.55
    p1 = (end[0] + size * math.cos(a1), end[1] + size * math.sin(a1))
    p2 = (end[0] + size * math.cos(a2), end[1] + size * math.sin(a2))
    draw.polygon([end, p1, p2], fill=fill)


def _draw_outline_circle(draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int, fill, width: int = 12):
    draw.ellipse((cx-r, cy-r, cx+r, cy+r), outline=fill, width=width)


def _render_archetype(
    background: Image.Image,
    out_path: Path,
    question: str,
    label: str,
    archetype: str,
    variant_index: int,
    topic: str,
) -> Path:
    img = _fit_background(background)
    # Give the background a richer, feed-friendly grade.
    img = ImageEnhance.Contrast(img).enhance(1.16)
    img = ImageEnhance.Color(img).enhance(1.18)
    base = img.filter(ImageFilter.GaussianBlur(radius=0.8))

    overlay = Image.new("RGBA", (THUMBNAIL_W, THUMBNAIL_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    # Darken edges + keep a high-clarity safe zone around the headline.
    for x in range(160):
        alpha = int(125 * (1 - x / 160))
        d.rectangle((x, 0, x + 1, THUMBNAIL_H), fill=(0, 0, 0, alpha))
    d.rectangle((0, 0, THUMBNAIL_W, THUMBNAIL_H), fill=(0, 0, 0, 32))
    d.rectangle((0, 0, 760, THUMBNAIL_H), fill=(0, 0, 0, 95))

    # Accent glow panels.
    cyan = (43, 222, 255, 235)
    yellow = (255, 213, 64, 255)
    red = (244, 54, 74, 255)
    white = (255, 255, 255, 255)
    dark = (5, 9, 18, 225)

    badge = _clean_text(label)[:24].upper() or "EXAMCRACKER AI"
    _rounded_box(d, (42, 34, 350, 88), 18, fill=dark, outline=yellow, width=3)
    d.text((68, 61), badge, font=_font(28), fill=yellow, anchor="lm")

    question = re.sub(r"\s+", " ", question).strip().upper().rstrip(".")
    if not question.endswith("?") and archetype not in {"trap", "number", "boss_fight"}:
        question += "?"
    if archetype == "trap":
        kicker = "EXAM TRAP"
    elif archetype == "countdown":
        kicker = "5 SECONDS"
    elif archetype == "compare":
        kicker = "A OR B?"
    elif archetype == "number":
        kicker = "CAN YOU REMEMBER?"
    elif archetype == "output":
        kicker = "FIND THE OUTPUT"
    elif archetype == "true_false":
        kicker = "TRUE OR TRAP?"
    elif archetype == "boss_fight":
        kicker = "BOSS FIGHT"
    elif archetype == "formula":
        kicker = "CRACK THE RULE"
    elif archetype == "mystery":
        kicker = "WAIT... WHY?"
    else:
        kicker = "CAN YOU GET THIS?"

    kicker_font = _font(34)
    title_font = _font(76)
    small_font = _font(26, bold=False)
    kicker_color = red if archetype in {"trap", "true_false"} else cyan
    d.text((54, 128), kicker, font=kicker_font, fill=kicker_color)

    # Headline: aggressive, compact, never more than 3 lines.
    maxw = 690 if variant_index % 2 == 0 else 720
    lines = _wrap_words(d, question, title_font, maxw)[:3]
    if not lines:
        lines = ["CAN YOU GET IT RIGHT?"]
    y = 208
    line_specs = []
    for line in lines:
        bbox = d.textbbox((0, 0), line, font=title_font, stroke_width=3)
        h = bbox[3] - bbox[1]
        line_specs.append((line, y, h, bbox[2]))
        y += h + 18
    # Draw all plates first, then all text, so stacked plates can never cover a
    # neighboring line of the headline.
    for line, line_y, h, text_w in line_specs:
        _rounded_box(d, (42, line_y - 10, min(748, 62 + text_w), line_y + h + 10), 16, fill=(3, 7, 14, 142))
    for line, line_y, _h, _text_w in line_specs:
        d.text((56, line_y), line, font=title_font, fill=white, stroke_width=4, stroke_fill=(0, 0, 0, 235))

    # Archetype-specific visual cues.
    if archetype == "compare":
        _rounded_box(d, (820, 420, 1215, 565), 28, fill=(5, 12, 24, 205), outline=cyan, width=6)
        d.text((1018, 492), "A   VS   B", font=_font(46), fill=white, anchor="mm")
        _draw_arrow(d, (780, 495), (1160, 495), yellow, width=12)
    elif archetype == "trap":
        _draw_outline_circle(d, 1030, 420, 125, red, width=13)
        d.text((1030, 420), "TRAP", font=_font(45), fill=white, anchor="mm", stroke_width=3, stroke_fill=(0,0,0,220))
        _draw_arrow(d, (810, 260), (930, 345), red, width=13)
    elif archetype == "countdown":
        _rounded_box(d, (840, 335, 1175, 560), 40, fill=(3, 10, 20, 215), outline=yellow, width=6)
        d.text((1006, 395), "5", font=_font(118), fill=yellow, anchor="mm", stroke_width=3, stroke_fill=(0,0,0,230))
        d.text((1006, 488), "SEC", font=_font(42), fill=white, anchor="mm")
    elif archetype == "number":
        d.text((1010, 460), "?", font=_font(190), fill=yellow, anchor="mm", stroke_width=8, stroke_fill=(0,0,0,230))
    elif archetype == "output":
        _rounded_box(d, (820, 320, 1190, 560), 26, fill=(2, 9, 18, 222), outline=cyan, width=5)
        d.text((855, 365), ">>>", font=_font(58), fill=cyan)
        d.text((855, 445), "?", font=_font(108), fill=yellow)
        _draw_arrow(d, (980, 388), (1120, 388), white, width=10)
    elif archetype == "true_false":
        _rounded_box(d, (790, 340, 1175, 470), 30, fill=(11, 86, 55, 220), outline=(90,255,170,255), width=5)
        _rounded_box(d, (790, 495, 1175, 625), 30, fill=(115, 15, 27, 220), outline=red, width=5)
        d.text((982, 404), "TRUE", font=_font(46), fill=white, anchor="mm")
        d.text((982, 559), "TRAP", font=_font(46), fill=white, anchor="mm")
    elif archetype == "formula":
        d.text((1000, 395), "=", font=_font(120), fill=yellow, anchor="mm", stroke_width=4, stroke_fill=(0,0,0,230))
        _draw_arrow(d, (810, 470), (1145, 470), cyan, width=12)
        d.text((1000, 535), "CRACK IT", font=_font(38), fill=white, anchor="mm")
    elif archetype == "boss_fight":
        _rounded_box(d, (810, 335, 1185, 585), 26, fill=(22, 6, 30, 220), outline=red, width=6)
        d.text((997, 410), "LEVEL", font=_font(34), fill=cyan, anchor="mm")
        d.text((997, 495), "01", font=_font(104), fill=yellow, anchor="mm", stroke_width=3, stroke_fill=(0,0,0,230))
    elif archetype == "mystery":
        _draw_outline_circle(d, 1005, 450, 128, cyan, width=8)
        d.text((1005, 450), "?", font=_font(150), fill=white, anchor="mm", stroke_width=5, stroke_fill=(0,0,0,230))
    else:  # question
        _draw_arrow(d, (790, 470), (1125, 360), yellow, width=12)
        d.text((1090, 555), "?", font=_font(125), fill=yellow, anchor="mm", stroke_width=4, stroke_fill=(0,0,0,230))

    # Bottom micro-CTA is intentionally tiny; the main visual remains the hook.
    d.text((54, 650), "EXAMCRACKER  •  QUICK CHALLENGE", font=small_font, fill=(238, 242, 247, 230))

    final = Image.alpha_composite(base.convert("RGBA"), overlay)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    final.convert("RGB").save(out_path, "JPEG", quality=94, optimize=True, progressive=True)
    return out_path


def _score_thumbnail(path: Path) -> float:
    """Lightweight deterministic quality score for candidate selection."""
    from PIL import ImageStat
    with Image.open(path) as opened:
        small = opened.convert("RGB").resize((320, 180))
        stat = ImageStat.Stat(small)
        contrast = sum(stat.stddev) / 3.0
        mean = sum(stat.mean) / 3.0
        # Favor bright, readable thumbnails without blowing highlights.
        brightness = max(0.0, 1.0 - abs(mean - 118.0) / 118.0)
        return contrast * 1.5 + brightness * 35.0


def create_custom_thumbnail(
    video_path: Path,
    out_path: Path,
    challenge_time: float,
    question: str,
    label: str,
    background_path: Path | None = None,
    topic: str = "",
    variants: int | None = None,
) -> Path:
    """Create 3+ premium 16:9 thumbnail candidates and select the best.

    When THUMBNAIL_AI_URL is set, each candidate asks a compatible image service
    (the bundled Z-Image-Turbo FastAPI server is one implementation) for a fresh
    text-free hero background. Without it, the pipeline still generates several
    materially different thumbnail layouts from the clean scene image.
    """
    count = max(1, int(variants or THUMBNAIL_VARIANTS))
    question = re.sub(r"\s+", " ", _clean_text(question)).strip()
    variant_dir = out_path.parent / "thumbnail_variants"
    variant_dir.mkdir(parents=True, exist_ok=True)

    seed_base = int(hashlib.md5(f"{topic}|{question}|{label}".encode("utf-8")).hexdigest()[:10], 16) % 10_000_000
    clean = _load_clean_background(video_path, background_path, challenge_time)
    candidates: list[Path] = []

    for i in range(count):
        archetype = _thumbnail_archetype(topic, question, i)
        seed = seed_base + i * 7919
        prompt = _thumbnail_visual_prompt(topic or label, question, archetype, seed)
        ai_img = _request_ai_background(prompt, seed)
        bg = ai_img if ai_img is not None else clean
        candidate = variant_dir / f"variant_{i+1:02d}_{archetype}.jpg"
        _render_archetype(bg, candidate, question, label, archetype, i, topic)
        candidates.append(candidate)

    ranked = sorted(candidates, key=_score_thumbnail, reverse=True)
    if not ranked:
        raise RuntimeError("No thumbnail candidates were produced")

    # Copy best candidate to the canonical output path; preserve all variants as
    # artifacts for manual comparison and future CTR experiments.
    best = ranked[0]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    Image.open(best).convert("RGB").save(out_path, "JPEG", quality=94, optimize=True, progressive=True)
    meta = {
        "question": question,
        "topic": topic,
        "label": label,
        "cloudflare_endpoint": cloudflare_configured(),
        "cloudflare_model": os.getenv("CLOUDFLARE_IMAGE_MODEL", "@cf/black-forest-labs/flux-1-schnell"),
        "variants": [p.name for p in ranked],
        "scores": {p.name: round(_score_thumbnail(p), 2) for p in candidates},
        "selected": best.name,
        "canvas": [THUMBNAIL_W, THUMBNAIL_H],
        "commercial_model_note": "AI image provider is endpoint-controlled; compositor is original Pillow code.",
    }
    (variant_dir / "manifest.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"[thumbnail] selected {best.name}; variants={len(candidates)} cloudflare={cloudflare_configured()}")
    return out_path
