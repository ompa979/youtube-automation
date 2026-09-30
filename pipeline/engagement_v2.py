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
V2_ACTION_SEQUENCE = ("hook", "context", "mechanism", "example", "exam_takeaway", "difference_card")

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
    return ""


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
    """V8 value-first contract with a final visual comparison scene."""
    defaults = {
        "hook": "WHY THIS MATTERS", "context": "THE CONTEXT", "mechanism": "HOW IT WORKS",
        "example": "WORKED EXAMPLE", "exam_takeaway": "EXAM CLUE", "difference_card": "KEY DIFFERENCE"
    }
    for i, scene in enumerate(script.scenes[:6]):
        role = V2_ACTION_SEQUENCE[i]
        scene.action_type = role
        scene.narration = _clean_text(getattr(scene, "narration", ""))
        scene.tts_text = _clean_text(getattr(scene, "tts_text", "")) or scene.narration
        scene.on_screen_text = _clean_text(getattr(scene, "on_screen_text", ""))[:60] or defaults[role]
        scene.action_payload = _clean_text(getattr(scene, "action_payload", ""))[:140]
        if role == "difference_card":
            scene.on_screen_text = "KEY DIFFERENCE"
            if not scene.action_payload:
                scene.action_payload = "KEY CONCEPT | KEY DISTINCTION"
    script.thumbnail_text = _clean_text(getattr(script, "thumbnail_text", ""))[:52].upper() or _clean_text(script.title)[:42].upper()


def build_comment_cta(script: "Script") -> str:
    return "What part of this concept should we explain with another example? Comment below."


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

# ═════════════════════════════════════════════════════════════════════════════
# CREATIVE V6 THUMBNAIL ENGINE
# ═════════════════════════════════════════════════════════════════════════════

_V6_THUMB_ARCHETYPES = (
    "hero_closeup",
    "cinematic_split",
    "concept_macro",
    "dramatic_diagram",
    "human_reaction",
    "object_transformation",
)
_V6_ACCENTS = (
    (255, 205, 54),   # warm yellow
    (36, 219, 255),   # electric cyan
    (255, 68, 86),    # red
    (255, 145, 40),   # orange
)
_V6_FONT_PATHS = (
    "/usr/share/fonts/opentype/inter/InterDisplay-Black.otf",
    "/usr/share/fonts/opentype/inter/Inter-Black.otf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
)
_V6_SEMI_PATHS = (
    "/usr/share/fonts/opentype/inter/InterDisplay-ExtraBold.otf",
    "/usr/share/fonts/opentype/inter/Inter-ExtraBold.otf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)


def _v6_thumb_font(size: int, heavy: bool = True):
    for path in (_V6_FONT_PATHS if heavy else _V6_SEMI_PATHS):
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def _v6_wrap(draw, text: str, font, max_width: int, max_lines: int = 2) -> list[str]:
    words = _clean_text(text).upper().split()
    lines: list[str] = []
    cur = ""
    for word in words:
        cand = word if not cur else f"{cur} {word}"
        if draw.textbbox((0, 0), cand, font=font, stroke_width=1)[2] <= max_width:
            cur = cand
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    if len(lines) <= max_lines:
        return lines
    # Force an even 2-line split for long copy.
    midpoint = max(1, len(words) // 2)
    left = " ".join(words[:midpoint])
    right = " ".join(words[midpoint:])
    while draw.textbbox((0, 0), left, font=font, stroke_width=1)[2] > max_width and " " in left:
        a, b = left.rsplit(" ", 1)
        right = (b + " " + right).strip()
        left = a
    return [left, right]


def _v6_dark_left(img: Image.Image) -> Image.Image:
    """Create a soft text-safe gradient without turning the thumbnail into a black card."""
    W, H = img.size
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    px = overlay.load()
    for x in range(W):
        t = max(0.0, 1.0 - x / (W * 0.58))
        a = int(118 * (t ** 1.6))
        for y in range(H):
            # Keep the art visible; only darken the text-safe region.
            vertical = 0.82 + 0.18 * (abs(y - H / 2) / (H / 2))
            px[x, y] = (0, 0, 0, min(132, int(a * vertical)))
    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")


def _v6_text_shadow(draw, xy, text, font, fill, anchor="la", stroke=0):
    x, y = xy
    draw.text((x + 6, y + 8), text, font=font, fill=(0, 0, 0, 210), anchor=anchor, stroke_width=max(5, stroke + 2), stroke_fill=(0, 0, 0, 180))
    draw.text(xy, text, font=font, fill=fill, anchor=anchor, stroke_width=stroke, stroke_fill=(5, 7, 12, 230))


def _v6_thumb_visual_prompt(topic: str, headline: str, archetype: str, subline: str) -> str:
    style = {
        "hero_closeup": "one dominant hero subject or character in a dramatic close-up, crisp foreground, shallow depth of field, expressive pose",
        "cinematic_split": "two concept elements staged in one premium composition, visually contrasting through scale, lighting and position rather than text",
        "concept_macro": "macro close-up of the exact real-world object or mechanism that represents the concept, tactile material detail",
        "dramatic_diagram": "premium 3D conceptual visualization with physical objects flowing through a mechanism, rich depth and clear causality",
        "human_reaction": "expressive young Indian learner reacting to a clearly recognizable concept object, cinematic portrait lighting and strong facial expression",
        "object_transformation": "a visually obvious before-to-after transformation of the exact concept, with motion frozen at the most dramatic moment",
    }[archetype]
    return (
        "Create a premium creator-style YouTube thumbnail hero image, designed as original commercial artwork rather than a video frame. "
        f"Topic: {topic}. Core curiosity: {headline}. Secondary meaning: {subline}. "
        f"Visual concept: {style}. Landscape 16:9. The RIGHT side contains the dominant subject; the LEFT side has controlled visual simplicity for later typography. "
        "Use strong foreground/background separation, realistic or high-end 3D materials, dramatic but clean cinematic lighting, vivid accent color, subtle particles or atmosphere, a strong focal light, layered depth, and a single unmistakable visual metaphor. "
        "The image should feel expensive, modern, editorial and highly clickable at small size. Avoid generic educational stock imagery. "
        "NO WORDS, NO LETTERS, NO NUMBERS, NO FAKE UI, NO LOGOS, NO WATERMARKS, NO BORDER, NO COLLAGE, NO CHEAP CLIPART. "
        "Reserve clean negative space on the LEFT for graphic typography added later in code."
    )


def _v6_thumbnail_render(background: Image.Image, out: Path, headline: str, subline: str, label: str, archetype: str, variant_index: int) -> Path:
    bg = _fit_background(background).convert("RGB")
    # Three distinct visual treatments keep a batch from looking templated.
    if variant_index % 3 == 0:
        bg = ImageEnhance.Contrast(bg).enhance(1.16)
        bg = ImageEnhance.Color(bg).enhance(1.24)
    elif variant_index % 3 == 1:
        bg = ImageEnhance.Contrast(bg).enhance(1.10)
        bg = ImageEnhance.Color(bg).enhance(1.08)
        bg = ImageEnhance.Brightness(bg).enhance(1.04)
    else:
        bg = ImageEnhance.Contrast(bg).enhance(1.20)
        bg = ImageEnhance.Color(bg).enhance(1.30)
        bg = ImageEnhance.Sharpness(bg).enhance(1.10)
    bg = _v6_dark_left(bg)

    canvas = bg.convert("RGBA")
    draw = ImageDraw.Draw(canvas)
    accent = _V6_ACCENTS[variant_index % len(_V6_ACCENTS)] + (255,)
    accent2 = _V6_ACCENTS[(variant_index + 1) % len(_V6_ACCENTS)] + (255,)

    # Premium graphic accents: glow, slash, rays and one concept cue.
    glow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for r, alpha in ((260, 20), (210, 28), (160, 38)):
        gd.ellipse((1000-r, 360-r, 1000+r, 360+r), fill=accent[:3] + (alpha,))
    glow = glow.filter(ImageFilter.GaussianBlur(18))
    canvas = Image.alpha_composite(canvas, glow)
    draw = ImageDraw.Draw(canvas)

    # Asymmetric editorial slash, not a UI panel.
    draw.polygon([(0, 592), (470, 448), (560, 468), (70, 648)], fill=accent[:3] + (125,))
    draw.polygon([(0, 648), (320, 557), (354, 574), (0, 690)], fill=accent2[:3] + (100,))
    draw.line((770, 76, 1226, 76), fill=(255,255,255,62), width=3)
    draw.line((770, 86, 1090, 86), fill=accent[:3] + (95,), width=5)

    # Small exam label; branding stays subordinate to the hook.
    badge = _clean_text(label).upper()[:22] or "EXAMCRACKER"
    badge_font = _v6_thumb_font(27, heavy=True)
    badge_w = draw.textbbox((0, 0), badge, font=badge_font)[2] + 42
    draw.rounded_rectangle((40, 34, 40 + badge_w, 82), radius=16, fill=(9, 12, 20, 210), outline=accent, width=3)
    draw.text((61, 58), badge, font=badge_font, fill=(255,255,255,255), anchor="lm")

    headline = re.sub(r"\s+", " ", headline).strip().upper()
    subline = re.sub(r"\s+", " ", subline).strip().upper()
    if len(headline) > 30:
        headline = headline[:30].rsplit(" ", 1)[0]
    if len(subline) > 36:
        subline = subline[:36].rsplit(" ", 1)[0]

    # Make the first line white and the last line an accent for an editorial punch.
    headline_font = _v6_thumb_font(92 if len(headline) < 20 else 82, heavy=True)
    sub_font = _v6_thumb_font(29, heavy=False)
    lines = _v6_wrap(draw, headline, headline_font, 610, 2)
    y = 148
    for idx, line in enumerate(lines):
        color = accent if idx == len(lines) - 1 else (255,255,255,255)
        _v6_text_shadow(draw, (46, y), line, headline_font, color, anchor="la", stroke=2)
        bbox = draw.textbbox((46, y), line, font=headline_font, anchor="la")
        if idx == len(lines) - 1:
            draw.rounded_rectangle((46, bbox[3] + 7, min(675, bbox[2] + 18), bbox[3] + 16), radius=5, fill=accent)
        y += 108

    if subline:
        # Compact editorial subline — no rectangular card.
        draw.text((48, 395), subline, font=sub_font, fill=(244,247,252,235), anchor="la",
                  stroke_width=1, stroke_fill=(0,0,0,150))

    # One bold graphic cue makes the thumbnail feel designed rather than merely composited.
    import math
    if "?" in headline or variant_index % 4 == 0:
        qfont = _v6_thumb_font(178, heavy=True)
        draw.text((1075, 82), "?", font=qfont, fill=accent[:3] + (175,), anchor="mm",
                  stroke_width=10, stroke_fill=(0,0,0,55))
    if archetype == "dramatic_diagram":
        draw.line((765, 560, 1115, 250), fill=accent[:3] + (235,), width=9)
        ang = math.atan2(250-560, 1115-765)
        pts = [(1115,250), (1115-38*math.cos(ang-0.55), 250-38*math.sin(ang-0.55)), (1115-38*math.cos(ang+0.55), 250-38*math.sin(ang+0.55))]
        draw.polygon(pts, fill=accent)
    elif archetype == "object_transformation":
        draw.line((765, 590, 1140, 590), fill=accent, width=12)
        draw.polygon([(1140,590),(1090,560),(1090,620)], fill=accent)
        for dx in (0, 20, 40):
            draw.ellipse((790+dx, 565, 802+dx, 577), fill=accent2[:3] + (210,))
    elif archetype == "concept_macro":
        draw.ellipse((910, 410, 1215, 715), outline=accent, width=10)
        draw.ellipse((940, 440, 1185, 685), outline=(255,255,255,120), width=3)
    elif archetype == "human_reaction":
        draw.arc((790, 120, 1210, 540), 208, 325, fill=accent2, width=8)
    elif archetype == "cinematic_split":
        draw.line((760, 150, 1165, 530), fill=accent[:3] + (225,), width=8)
        draw.ellipse((1120, 485, 1178, 543), fill=accent2[:3] + (210,))
    else:
        draw.arc((820, 410, 1240, 830), 198, 332, fill=accent[:3] + (165,), width=7)

    # Tiny brand signature only.
    mark_font = _v6_thumb_font(18, heavy=False)
    draw.text((46, 684), "EXAMCRACKER AI", font=mark_font, fill=(235,240,248,145))

    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(out, "JPEG", quality=97, optimize=True, progressive=True)
    return out


def _v6_score_thumbnail(path: Path) -> float:
    """Score for thumbnail readability + visual energy + left/right composition."""
    from PIL import ImageStat, ImageFilter
    with Image.open(path) as im:
        im = im.convert("RGB").resize((320, 180))
        stat = ImageStat.Stat(im)
        mean = sum(stat.mean) / 3.0
        contrast = sum(stat.stddev) / 3.0
        saturation = max(stat.mean) - min(stat.mean)
        brightness = max(0.0, 1.0 - abs(mean - 126.0) / 126.0)
        edges = im.filter(ImageFilter.FIND_EDGES).convert("L")
        e = ImageStat.Stat(edges).mean[0]
        left = ImageStat.Stat(im.crop((0, 0, 150, 180)).filter(ImageFilter.FIND_EDGES)).mean[0]
        right = ImageStat.Stat(im.crop((165, 0, 320, 180)).filter(ImageFilter.FIND_EDGES)).mean[0]
        composition = max(0.0, min(20.0, (right - left) * 0.8 + 8.0))
        return contrast * 1.7 + brightness * 26.0 + saturation * 0.5 + e * 0.5 + composition


def create_custom_thumbnail(
    video_path: Path,
    out_path: Path,
    challenge_time: float,
    question: str,
    label: str,
    background_path: Path | None = None,
    topic: str = "",
    variants: int | None = None,
    subline: str = "",
    visual_prompt: str = "",
) -> Path:
    """V6 premium thumbnail engine: AI hero art + original deterministic typography."""
    count = max(3, int(variants or THUMBNAIL_VARIANTS))
    headline = _clean_text(question).strip(" ?!.:").upper() or "LEARN THIS FAST"
    secondary = _clean_text(subline).upper()
    if not secondary:
        # Derive a compact concept line from the topic instead of inventing a generic A/B game.
        secondary = _concept_from_topic(topic, headline).upper()[:32]
    variant_dir = out_path.parent / "thumbnail_variants"
    variant_dir.mkdir(parents=True, exist_ok=True)
    seed_base = int(hashlib.sha1(f"{topic}|{headline}|{secondary}|{label}".encode("utf-8")).hexdigest()[:10], 16)
    clean = _load_clean_background(video_path, background_path, challenge_time)
    candidates: list[Path] = []

    for i in range(count):
        archetype = _V6_THUMB_ARCHETYPES[i % len(_V6_THUMB_ARCHETYPES)]
        seed = seed_base + i * 7919
        prompt = _clean_text(visual_prompt) if visual_prompt else _v6_thumb_visual_prompt(topic or label, headline, archetype, secondary)
        # Add the archetype-specific composition constraints even when Gemini authored the brief.
        prompt = prompt + (" Landscape 16:9. RIGHT-side hero subject, LEFT-side clean negative space for typography. NO WORDS, NO LETTERS, NO NUMBERS, NO LOGOS, NO WATERMARKS.")
        ai_img = _request_ai_background(prompt, seed)
        bg = ai_img if ai_img is not None else clean
        candidate = variant_dir / f"v6_{i+1:02d}_{archetype}.jpg"
        _v6_thumbnail_render(bg, candidate, headline, secondary, label, archetype, i)
        candidates.append(candidate)

    ranked = sorted(candidates, key=_v6_score_thumbnail, reverse=True)
    best = ranked[0]
    Image.open(best).convert("RGB").save(out_path, "JPEG", quality=96, optimize=True, progressive=True)
    manifest = {
        "engine": "creative_v6_premium_art",
        "headline": headline,
        "subline": secondary,
        "topic": topic,
        "label": label,
        "variants": [p.name for p in ranked],
        "scores": {p.name: round(_v6_score_thumbnail(p), 2) for p in candidates},
        "selected": best.name,
        "canvas": [THUMBNAIL_W, THUMBNAIL_H],
        "ai_provider": os.getenv("CLOUDFLARE_THUMBNAIL_MODEL", "@cf/black-forest-labs/flux-2-klein-4b"),
        "visual_prompt_source": "script.thumbnail_visual_prompt" if visual_prompt else "engine_archetype_prompt",
    }
    (variant_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"[thumbnail-v6] selected={best.name} headline={headline!r} subline={secondary!r}")
    return out_path


# ═════════════════════════════════════════════════════════════════════════════
# CREATIVE V7 — natural teaching, premium packaging, NO GAME-SHOW COPY
# ═════════════════════════════════════════════════════════════════════════════

V2_ACTION_SEQUENCE = ("hook", "context", "mechanism", "example", "exam_takeaway", "difference_card")

_V7_BANNED = re.compile(
    r"\b(?:A\s*(?:OR|VS\.?|VERSUS)\s*B|QUICK TEST|THINK FAST|COUNTDOWN|STOP SCROLLING|STOP|REVEAL|THE TRICK|DID YOU GET IT)\b",
    re.I,
)


def _v7_clean(value: str) -> str:
    text = _clean_text(value)
    text = re.sub(r"\bA\s*(?:OR|VS\.?|VERSUS)\s*B\b", "", text, flags=re.I)
    text = re.sub(r"\b(?:QUICK TEST|THINK FAST|COUNTDOWN|STOP SCROLLING|STOP|REVEAL|THE TRICK|DID YOU GET IT)\b", "", text, flags=re.I)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip(" -:|,;")


def _v7_question(script: "Script") -> str:
    """Create a natural, concept-specific question for the description/pinned comment."""
    if not getattr(script, "scenes", None):
        return "What part of this concept would you like explained next?"
    for scene in script.scenes:
        text = _clean_text(getattr(scene, "narration", ""))
        m = re.search(r"([^.!?]*\?)", text)
        if m:
            q = _v7_clean(m.group(1)).strip()
            if q and len(q) <= 110:
                return q
    last = _clean_text(getattr(script.scenes[-1], "narration", ""))
    concept = _clean_text(last[:90]).rstrip(".,;:!? ")
    return f"Which part of this concept was most useful: {concept}?"


def build_comment_cta(script: "Script") -> str:
    """Turn the final memory rule into a useful pinned comment, not a quiz CTA."""
    scenes = getattr(script, "scenes", []) or []
    memory = _clean_text(getattr(scenes[-1], "narration", "")) if scenes else ""
    memory = _v7_clean(memory).rstrip(".?! ")
    if len(memory) > 120:
        memory = memory[:120].rsplit(" ", 1)[0]
    if memory:
        return f"Save this rule: {memory}. What exam concept should we break down next? Comment below."
    return "What exam concept should we break down next? Comment below."


def build_thumbnail_text(script: "Script") -> str:
    """Return a bold value-led thumbnail phrase; never a quiz option prompt."""
    text = _clean_text(getattr(script, "thumbnail_text", ""))
    cleaned = _v7_clean(text).upper()
    if 2 <= len(cleaned.split()) <= 7:
        return cleaned[:42]
    for scene in getattr(script, "scenes", []):
        candidate = _v7_clean(getattr(scene, "on_screen_text", ""))
        if 2 <= len(candidate.split()) <= 6:
            return candidate.upper()[:42]
    return _clean_text(getattr(script, "title", ""))[:42].upper()


def build_click_title(topic: str, base_title: str, script: "Script") -> str:
    """Search-first title: exact concept + useful outcome, no game-show gimmicks."""
    concept = _clean_text(topic)
    if ":" in concept:
        concept = concept.split(":", 1)[0].strip()
    concept = re.sub(r"^(?:IBPS|SBI|RBI|UPSC|SSC|GATE)[^:|\-–—]*[:|\-–—]\s*", "", concept, flags=re.I).strip()
    if not concept:
        concept = _clean_text(base_title)
    # Use a natural benefit based on the topic itself.
    low = topic.lower()
    if " vs " in low or "versus" in low or "difference" in low:
        suffix = "The Key Difference"
    elif "how" in low or "works" in low:
        suffix = "How It Actually Works"
    elif "rule" in low or "classification" in low or "property" in low:
        suffix = "The Rule You Need"
    elif "shortcut" in low or "trick" in low:
        suffix = "The Fastest Safe Method"
    else:
        suffix = "Explained With an Example"
    title = f"{concept}: {suffix}"
    exam = _exam_label(topic, base_title)
    if exam != "EXAMCRACKER AI" and exam.lower() not in title.lower():
        addition = f" | {exam}"
        if len(title) + len(addition) <= 85:
            title += addition
    return re.sub(r"\s+", " ", title).strip(" -:|")[:85]


def enforce_v2_contract(script: "Script") -> None:
    """Normalize to six teaching beats without overwriting good copy."""
    if not getattr(script, "scenes", None):
        return
    for i, scene in enumerate(script.scenes[:6]):
        role = V2_ACTION_SEQUENCE[i]
        scene.action_type = role
        scene.narration = _v7_clean(getattr(scene, "narration", ""))
        scene.tts_text = _v7_clean(getattr(scene, "tts_text", "")) or scene.narration
        scene.on_screen_text = _v7_clean(getattr(scene, "on_screen_text", ""))[:60]
        scene.action_payload = _v7_clean(getattr(scene, "action_payload", ""))[:180]
        if not scene.on_screen_text:
            defaults = {
                "hook": "WHY IT MATTERS",
                "context": "WHAT CHANGES",
                "mechanism": "HOW IT WORKS",
                "example": "WORKED EXAMPLE",
                "exam_takeaway": "LOOK FOR THIS",
                "difference_card": "KEY DIFFERENCE",
                "memory_lock": "REMEMBER THE RULE",
            }
            scene.on_screen_text = defaults[role]
    if not getattr(script, "thumbnail_text", ""):
        script.thumbnail_text = build_thumbnail_text(script)

# V7 thumbnail helpers — text is added after AI art, with a clean editorial layout.
_V7_THUMB_ARCHETYPES = (
    "editorial_hero", "cinematic_split", "concept_macro", "human_reaction", "transformation",
    "exploded_view", "spotlight_subject", "dynamic_arrow", "cutaway_3d", "warning_diagonal",
)


def _v7_visual_prompt(topic: str, headline: str, archetype: str, subline: str) -> str:
    styles = {
        "editorial_hero": "one unforgettable hero subject, large in frame, expressive action, crisp silhouette, shallow depth of field",
        "cinematic_split": "two real concept elements interacting in one composition, strong directional separation, no text",
        "concept_macro": "extreme-detail close-up of the exact object or mechanism that represents the concept",
        "human_reaction": "an expressive young Indian learner with a clear reaction beside the exact concept object, cinematic portrait lighting",
        "transformation": "a frozen instant of a clear before-to-after transformation of the concept, with motion implied by particles and directional light",
        "exploded_view": "a premium exploded-view composition showing the parts of the concept separated in space with precise physical relationships",
        "spotlight_subject": "one iconic subject under a dramatic studio spotlight, with rich environment detail and a strong rim light",
        "dynamic_arrow": "a dynamic directional composition where the real concept object visibly travels from one state to another",
        "cutaway_3d": "a sophisticated 3D cutaway revealing the internal mechanism of the concept with realistic materials and layered depth",
        "warning_diagonal": "a high-energy editorial composition with one clear mistake/correction visual and bold diagonal motion cues",
    }
    return (
        "Create a stunning, premium, creator-grade YouTube thumbnail HERO IMAGE that feels like top-tier social creative, not a screenshot, lesson slide, stock photo, or template. "
        f"Topic: {topic}. Main idea: {headline}. Context: {subline}. "
        f"Art direction: {styles[archetype]}. Landscape 16:9. "
        "Design for a tiny mobile thumbnail first: one unforgettable focal subject, immediate visual storytelling, strong silhouette, aggressive but tasteful depth, cinematic lens perspective, believable motion, rich material detail, bright focal highlight, premium color contrast, controlled shadows, subtle glow, depth haze, and a polished advertising/editorial finish. "
        "Make the scene feel expensive and energetic: glossy or tactile materials, realistic reflections, directional light, rich environmental context, layered foreground/midground/background, and one decisive visual action that explains the idea. "
        "Place the hero subject on the RIGHT 55-65% of the canvas and keep the LEFT 35-45% visually simpler but still cinematic so later typography can sit there without covering the hero. "
        "Do NOT use flat black backgrounds, generic neon wallpaper, classroom stock photos, cheap clipart, fake dashboards, infographic grids, random decorative symbols, repetitive circles, tiny unreadable detail, or poster/card layouts. "
        "Think: premium creator thumbnail + cinematic advertisement + photorealistic concept art. The image itself must be memorable before any text is added. "
        "NO WORDS, NO LETTERS, NO NUMBERS, NO LOGOS, NO WATERMARKS, NO BORDERS, NO COLLAGE."
    )


def _v7_thumbnail_render(background: Image.Image, out: Path, headline: str, subline: str, label: str, archetype: str, idx: int) -> Path:
    import math
    bg = _fit_background(background).convert("RGB")
    bg = ImageEnhance.Contrast(bg).enhance(1.22)
    bg = ImageEnhance.Color(bg).enhance(1.20)
    bg = ImageEnhance.Sharpness(bg).enhance(1.10)

    canvas = bg.convert("RGBA")
    # soft left vignette, never a solid card
    grad = Image.new("RGBA", canvas.size, (0,0,0,0))
    gd = ImageDraw.Draw(grad)
    for x in range(760):
        t = x/760.0
        a = int(112 * (1-t)**1.8)
        gd.line((x,0,x,720), fill=(0,0,0,a))
    canvas = Image.alpha_composite(canvas, grad)
    draw = ImageDraw.Draw(canvas)
    accent = _V6_ACCENTS[idx % len(_V6_ACCENTS)] + (255,)
    accent2 = _V6_ACCENTS[(idx+2) % len(_V6_ACCENTS)] + (255,)

    badge = _clean_text(label).upper()[:20]
    badge_font = _v6_thumb_font(27, heavy=True)
    draw.text((48, 42), badge, font=badge_font, fill=(255,255,255,245), stroke_width=2, stroke_fill=(0,0,0,190))
    draw.line((48, 88, 270, 88), fill=accent, width=7)

    headline = _v7_clean(headline).upper()[:34]
    subline = _v7_clean(subline).upper()[:40]
    font_size = 88 if len(headline) <= 18 else 76
    hfont = _v6_thumb_font(font_size, heavy=True)
    sfont = _v6_thumb_font(30, heavy=False)
    lines = _v6_wrap(draw, headline, hfont, 640, 2)[:2]
    y = 150
    for j, line in enumerate(lines):
        color = (255,255,255,255) if j == 0 else accent
        _v6_text_shadow(draw, (48, y), line, hfont, color, anchor="la", stroke=3)
        y += font_size + 8
    if subline:
        draw.text((50, min(430, y+8)), subline, font=sfont, fill=(240,244,250,238), stroke_width=2, stroke_fill=(0,0,0,185))

    # One strong graphic mark, no UI panels.
    if archetype == "cinematic_split":
        draw.line((760, 120, 1190, 600), fill=accent, width=10)
    elif archetype == "concept_macro":
        draw.ellipse((985, 310, 1190, 515), outline=accent, width=10)
    elif archetype == "human_reaction":
        draw.arc((850, 90, 1220, 450), 210, 325, fill=accent2, width=9)
    elif archetype == "transformation":
        draw.line((820, 610, 1165, 610), fill=accent, width=13)
        draw.polygon([(1165,610),(1108,572),(1108,648)], fill=accent)
    else:
        draw.arc((860, 400, 1240, 790), 205, 325, fill=accent2, width=8)

    mark_font = _v6_thumb_font(18, heavy=False)
    draw.text((48, 688), "EXAMCRACKER AI", font=mark_font, fill=(238,242,247,150))
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(out, "JPEG", quality=97, optimize=True, progressive=True)
    return out


def _v11_procedural_hero(topic: str, variant: int) -> Image.Image:
    """High-contrast concept art fallback when all thumbnail AI accounts are exhausted."""
    from PIL import ImageDraw, ImageFilter
    img = Image.new("RGB", (THUMBNAIL_W, THUMBNAIL_H), (10, 17, 32))
    draw = ImageDraw.Draw(img, "RGBA")
    # Soft radial-like bands give the fallback a designed, non-screenshot look.
    for r in range(520, 20, -20):
        alpha = int(5 + (520 - r) * 0.08)
        draw.ellipse((850-r, 360-r, 850+r, 360+r), fill=(20, 120, 220, alpha))
    core = _v11_core_topic(topic)
    low = core.lower()

    def node(x, y, r, fill=(40, 190, 255, 210)):
        draw.ellipse((x-r, y-r, x+r, y+r), fill=(4, 10, 24, 230), outline=fill, width=8)
        draw.ellipse((x-r//2, y-r//2, x+r//2, y+r//2), fill=fill)

    if re.search(r"tcp.*3-way|3-way.*handshake|syn.*syn-ack", low):
        pts = [(820, 180), (1060, 360), (820, 540)]
        node(*pts[0], 56); node(*pts[1], 72, (255, 194, 66, 230)); node(*pts[2], 56, (88, 220, 160, 230))
        for a,b in zip(pts, pts[1:]):
            draw.line((*a, *b), fill=(230, 240, 255, 200), width=12)
        draw.arc((745, 250, 980, 480), 310, 155, fill=(255, 110, 75, 230), width=10)
        draw.polygon([(985, 332), (950, 318), (965, 350)], fill=(255, 110, 75, 230))
    elif re.search(r"deadlock|coffman", low):
        pts = [(850, 200), (1060, 260), (1040, 500), (800, 540)]
        for i,(x,y) in enumerate(pts):
            node(x,y,58, [(70,200,255,230),(255,190,65,230),(90,225,170,230),(240,95,110,230)][i])
        for i in range(4):
            a,b=pts[i],pts[(i+1)%4]
            draw.line((*a,*b), fill=(245,245,255,180), width=10)
    elif re.search(r"crr|slr|repo|npa|bank|finance", low):
        draw.rounded_rectangle((820, 150, 1080, 570), 34, fill=(28, 42, 66, 230), outline=(100, 185, 255, 230), width=8)
        draw.ellipse((875, 205, 1025, 355), fill=(255, 195, 64, 230))
        for y in (410, 470, 530):
            draw.rectangle((875, y, 1025, y+30), fill=(86, 206, 177, 210))
        draw.line((770, 170, 770, 560), fill=(240,245,255,150), width=8)
        draw.line((770, 365, 820, 365), fill=(240,245,255,200), width=10)
    elif re.search(r"sql|database|normalization|query", low):
        for y in (210, 350, 490):
            draw.ellipse((820, y, 1040, y+70), fill=(65, 155, 240, 220), outline=(220,245,255,190), width=6)
            draw.rectangle((820, y+35, 1040, y+105), fill=(24,55,90,230), outline=(220,245,255,120), width=6)
        draw.polygon([(1080, 270), (1190, 270), (1150, 450), (1120, 450)], fill=(255,190,70,210))
    else:
        cx = 950 + (variant % 3) * 20
        cy = 360
        for r, fill in ((170,(35,125,255,60)), (120,(45,190,240,80)), (70,(255,190,70,150))):
            draw.ellipse((cx-r,cy-r,cx+r,cy+r), fill=fill, outline=(230,245,255,150), width=5)
        draw.line((800, 570, 1100, 160), fill=(95,220,190,190), width=14)
        draw.polygon([(1100,160),(1065,180),(1080,212)], fill=(95,220,190,220))
    return img.filter(ImageFilter.GaussianBlur(0.15))


def create_custom_thumbnail(video_path: Path, out_path: Path, challenge_time: float, question: str, label: str,
                            background_path: Path | None = None, topic: str = "", variants: int | None = None,
                            subline: str = "", visual_prompt: str = "") -> Path:
    """V7 premium thumbnail: AI hero art first, typography second, no stale HUD-card look."""
    count = max(3, int(variants or int(os.getenv("THUMBNAIL_VARIANTS", "3"))))
    headline = _v7_clean(question or "").upper().strip(" ?!.") or "LEARN THIS RULE"
    secondary = _v7_clean(subline) or _concept_from_topic(topic, headline)
    variant_dir = out_path.parent / "thumbnail_variants"
    variant_dir.mkdir(parents=True, exist_ok=True)
    seed_base = int(hashlib.sha1(f"{topic}|{headline}|{secondary}|{label}".encode()).hexdigest()[:10], 16)
    clean = _load_clean_background(video_path, background_path, challenge_time)
    candidates=[]
    for i in range(count):
        start_index = seed_base % len(_V7_THUMB_ARCHETYPES)
        archetype = _V7_THUMB_ARCHETYPES[(start_index + i) % len(_V7_THUMB_ARCHETYPES)]
        prompt = _clean_text(visual_prompt) if visual_prompt else _v7_visual_prompt(topic or label, headline, archetype, secondary)
        prompt += " Landscape 16:9; hero weighted to right; premium commercial thumbnail art; no text."
        try:
            ai_img = _request_ai_background(prompt, seed_base + i*7919)
        except Exception as exc:
            print(f"[thumbnail-v7] AI variant {i+1} failed: {exc}")
            ai_img = None
        bg = ai_img if ai_img is not None else clean
        candidate = variant_dir / f"v7_{i+1:02d}_{archetype}.jpg"
        _v7_thumbnail_render(bg, candidate, headline, secondary, label, archetype, i)
        candidates.append(candidate)
    ranked = sorted(candidates, key=_v6_score_thumbnail, reverse=True)
    best = ranked[0]
    Image.open(best).convert("RGB").save(out_path, "JPEG", quality=97, optimize=True, progressive=True)
    manifest={"engine":"creative_v7_premium_hero","headline":headline,"subline":secondary,"selected":best.name,
              "variants":[p.name for p in ranked],"scores":{p.name:round(_v6_score_thumbnail(p),2) for p in candidates},
              "canvas":[1280,720],"ai_provider":os.getenv("CLOUDFLARE_THUMBNAIL_MODEL", os.getenv("CLOUDFLARE_IMAGE_MODEL", "@cf/black-forest-labs/flux-2-klein-4b"))}
    (variant_dir/"manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"[thumbnail-v7] selected={best.name} headline={headline!r} subline={secondary!r}")
    return out_path


# V8 thumbnail override: layout-aware AI hero art first, deterministic typography second.
_V8_LAYOUTS = ("hero_right_text_left", "hero_left_text_right", "center_hero_top_text", "split_concepts", "giant_number", "human_reaction_right")
_V8_ACCENTS = ((255,208,52),(43,221,255),(255,76,84),(255,145,46))

def _v8_thumbnail_visual_prompt(topic: str, headline: str, subline: str, layout: str) -> str:
    layout_map = {
        "hero_right_text_left":"hero subject dominates the RIGHT 58 percent; LEFT 38 percent is clean cinematic negative space; no important object in the left text zone",
        "hero_left_text_right":"hero subject dominates the LEFT 55 percent; RIGHT 40 percent is clean cinematic negative space; no important object in the right text zone",
        "center_hero_top_text":"hero sits below center; upper third is uncluttered for headline; subject remains visually dominant",
        "split_concepts":"two exact concept objects separated clearly left and right; strong visual contrast; no text",
        "giant_number":"one unmistakable concept object on the RIGHT with depth; LEFT stays simple for giant typography",
        "human_reaction_right":"expressive young Indian learner on the RIGHT beside the exact concept object; LEFT remains quiet for typography",
    }
    return ("Create a premium creator-grade YouTube thumbnail hero image, not a lesson slide, not a stock photo, not an infographic and not a video frame. "
            f"Topic: {topic}. Core idea: {headline}. Supporting meaning: {subline}. Composition: {layout_map[layout]}. "
            "Use one unforgettable focal subject, one decisive physical action, strong cinematic perspective, realistic or high-end 3D materials, crisp foreground/background separation, directional key light, rim light, rich reflections, atmospheric depth, vivid but controlled color, expensive advertising finish and a memorable silhouette. "
            "The image must explain the concept when muted and reserve the specified text-safe area. Absolutely NO words, letters, numbers, logos, watermarks, UI, infographic panels, borders or collage. Landscape 16:9, designed for 1280x720.")

def _v8_detect_text_side(img: Image.Image, preferred: str) -> str:
    """Choose the quieter half of the AI artwork for typography using edge density."""
    small = img.convert("L").resize((320, 180))
    edges = small.filter(ImageFilter.FIND_EDGES)
    import numpy as _np
    arr = _np.asarray(edges, dtype=_np.float32)
    mid = arr.shape[1] // 2
    left = float(arr[:, :mid].mean())
    right = float(arr[:, mid:].mean())
    if abs(left - right) < 4.0:
        return "left" if "left" in preferred else "right"
    return "left" if left < right else "right"


def _v8_fit_text(draw, text, max_width, max_lines=2, start=82, minimum=48):
    for size in range(start, minimum - 1, -2):
        font = _v6_thumb_font(size, heavy=True)
        lines = _v6_wrap(draw, text, font, max_width, max_lines)
        widths = [draw.textbbox((0,0), line, font=font)[2] for line in lines]
        if len(lines) <= max_lines and (not widths or max(widths) <= max_width):
            return font, lines
    font = _v6_thumb_font(minimum, heavy=True)
    return font, _v6_wrap(draw, text, font, max_width, max_lines)


def _v8_gradient(draw, side: str):
    if side == "left":
        width = 690
        for x in range(width):
            t = x / max(1, width - 1)
            alpha = int(170 * ((1 - t) ** 1.8))
            draw.line((x, 0, x, THUMBNAIL_H), fill=(0, 0, 0, alpha))
    else:
        start = THUMBNAIL_W - 690
        for x in range(start, THUMBNAIL_W):
            t = (x - start) / max(1, 690 - 1)
            alpha = int(170 * (t ** 1.8))
            draw.line((x, 0, x, THUMBNAIL_H), fill=(0, 0, 0, alpha))


def _v8_thumbnail_render(background, out, headline, subline, label, layout, variant_index):
    bg=_fit_background(background).convert("RGB")
    bg=ImageEnhance.Contrast(bg).enhance(1.18); bg=ImageEnhance.Color(bg).enhance(1.13); bg=ImageEnhance.Sharpness(bg).enhance(1.12)
    canvas=bg.convert("RGBA"); draw=ImageDraw.Draw(canvas)
    preferred = "right" if "right" in layout or layout == "split_concepts" else "left"
    side = "left" if layout == "center_hero_top_text" else _v8_detect_text_side(bg, preferred)
    accent=_V8_ACCENTS[variant_index%len(_V8_ACCENTS)]+(255,)
    accent2=_V8_ACCENTS[(variant_index+1)%len(_V8_ACCENTS)]+(255,)
    _v8_gradient(draw, side)
    if side == "left":
        text_x, max_width = 48, 575
    else:
        text_x, max_width = 692, 480
    badge=_clean_text(label).upper()[:20] or "EXAMCRACKER"
    bf=_v6_thumb_font(22,heavy=True)
    badge_w=max(190,min(330,draw.textbbox((0,0),badge,font=bf)[2]+34))
    draw.rounded_rectangle((text_x,28,text_x+badge_w,72),radius=13,fill=(3,8,15,225),outline=accent,width=2)
    draw.text((text_x+16,50),badge,font=bf,fill=(255,255,255,255),anchor="lm")
    h=re.sub(r"\s+"," ",_clean_text(headline)).upper().strip("?!:;,. ")[:40]
    sub=re.sub(r"\s+"," ",_clean_text(subline)).upper()[:34]
    hf, lines = _v8_fit_text(draw, h, max_width, max_lines=2, start=82, minimum=50)
    y=118
    line_heights=[]
    for line in lines:
        bbox=draw.textbbox((0,0),line,font=hf,stroke_width=3); line_heights.append(bbox[3]-bbox[1])
    for idx,line in enumerate(lines):
        fill=(255,255,255,255) if idx < len(lines)-1 else accent
        draw.text((text_x,y),line,font=hf,fill=fill,stroke_width=5,stroke_fill=(0,0,0,235))
        y += line_heights[idx] + 10
    if sub:
        sf=_v6_thumb_font(27,heavy=False)
        draw.text((text_x,y+8),sub,font=sf,fill=(248,250,255,248),stroke_width=2,stroke_fill=(0,0,0,200))
    # One graphic cue only; never a giant question mark that can collide with the hero.
    if "?" in h:
        qx = text_x + max_width - 8
        draw.text((qx,128),"?",font=_v6_thumb_font(112,heavy=True),fill=accent2[:3]+(185,),anchor="ra",stroke_width=7,stroke_fill=(0,0,0,120))
    # Small separator and brand; never encroach on the hero area.
    draw.line((text_x,650,min(text_x+260,text_x+max_width),650),fill=accent,width=5)
    draw.text((text_x,684),"EXAMCRACKER AI",font=_v6_thumb_font(15,heavy=False),fill=(235,240,248,165))
    out.parent.mkdir(parents=True,exist_ok=True); canvas.convert("RGB").save(out,"JPEG",quality=97,optimize=True,progressive=True); return out

def create_custom_thumbnail(video_path, out_path, challenge_time, question, label, background_path=None, topic="", variants=None, subline="", visual_prompt=""):
    count=max(3,int(variants or int(os.getenv("THUMBNAIL_VARIANTS","3"))))
    headline=_clean_text(question).strip("?!:;,. ").upper() or "KEY RULE"; secondary=_clean_text(subline).upper() or "KEY CONCEPT"
    vdir=out_path.parent/"thumbnail_variants"; vdir.mkdir(parents=True,exist_ok=True)
    seed_base=int(hashlib.sha1(f"v8|{topic}|{headline}|{secondary}|{label}".encode()).hexdigest()[:10],16)
    clean=_load_clean_background(video_path,background_path,challenge_time); candidates=[]
    for i in range(count):
        layout=_V8_LAYOUTS[i%len(_V8_LAYOUTS)]; prompt=_v8_thumbnail_visual_prompt(topic or label,headline,secondary,layout)
        try: ai=_request_ai_background(prompt,seed_base+i*7919)
        except Exception as exc: print(f"[thumbnail-v8] AI candidate {i+1} failed: {exc}"); ai=None
        bg=ai or clean; path=vdir/f"v8_{i+1:02d}_{layout}.jpg"; _v8_thumbnail_render(bg,path,headline,secondary,label,layout,i); candidates.append(path)
    ranked=sorted(candidates,key=_v6_score_thumbnail,reverse=True); best=ranked[0]
    Image.open(best).convert("RGB").save(out_path,"JPEG",quality=97,optimize=True,progressive=True)
    (vdir/"manifest.json").write_text(json.dumps({"engine":"v8_layout_aware","selected":best.name,"variants":[p.name for p in ranked],"scores":{p.name:round(_v6_score_thumbnail(p),2) for p in candidates},"canvas":[THUMBNAIL_W,THUMBNAIL_H],"model":os.getenv("CLOUDFLARE_THUMBNAIL_MODEL","@cf/black-forest-labs/flux-2-klein-4b")},indent=2),encoding="utf-8")
    print(f"[thumbnail-v8] selected={best.name}; variants={len(candidates)}")
    return out_path

# ═════════════════════════════════════════════════════════════════════════════
# CREATIVE V10 — art-directed thumbnails, image-first composition, no template sludge
# ═════════════════════════════════════════════════════════════════════════════

def _v10_fit_headline(draw, text: str, max_width: int, max_height: int = 260):
    clean = re.sub(r"\s+", " ", _clean_text(text)).upper().strip("?!:;,. ")
    words = clean.split()[:5]
    clean = " ".join(words) or "THE KEY DIFFERENCE"
    for size in range(100, 47, -2):
        font = _v6_thumb_font(size, heavy=True)
        lines = _v6_wrap(draw, clean, font, max_width, 3)
        heights = []
        widths = []
        for line in lines:
            box = draw.textbbox((0, 0), line, font=font, stroke_width=3)
            widths.append(box[2] - box[0]); heights.append(box[3] - box[1])
        if len(lines) <= 3 and max(widths or [0]) <= max_width and sum(heights) + 18 * max(0, len(lines)-1) <= max_height:
            return font, lines
    font = _v6_thumb_font(48, heavy=True)
    return font, _v6_wrap(draw, clean, font, max_width, 3)


def _v10_apply_text_zone(canvas: Image.Image, zone: str, box: tuple[int,int,int,int], headline: str, subline: str, label: str, variant: int) -> None:
    draw = ImageDraw.Draw(canvas)
    x1, y1, x2, y2 = box
    accent = _V6_ACCENTS[variant % len(_V6_ACCENTS)] + (255,)
    accent2 = _V6_ACCENTS[(variant + 2) % len(_V6_ACCENTS)] + (255,)
    zone_w = x2 - x1
    grad = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    if zone == "left":
        for x in range(max(0, x1-40), min(canvas.width, x2+130)):
            t = (x - max(0, x1-40)) / max(1, (x2+130) - max(0, x1-40))
            a = int(125 * (1 - t) ** 1.7)
            gd.line((x, 0, x, canvas.height), fill=(0, 0, 0, a))
    else:
        for x in range(max(0, x1-130), min(canvas.width, x2+40)):
            t = (x - max(0, x1-130)) / max(1, (x2+40) - max(0, x1-130))
            a = int(125 * t ** 1.7)
            gd.line((x, 0, x, canvas.height), fill=(0, 0, 0, a))
    canvas.alpha_composite(grad)
    draw = ImageDraw.Draw(canvas)

    tx = x1 + 12
    maxw = max(260, zone_w - 24)
    label_text = _clean_text(label).upper()[:22]
    if label_text:
        lf = _v6_thumb_font(22, heavy=True)
        draw.text((tx, y1 + 12), label_text, font=lf, fill=(245, 248, 252, 230), stroke_width=2, stroke_fill=(0,0,0,185))
        draw.line((tx, y1 + 48, min(tx + 170, x2), y1 + 48), fill=accent, width=5)

    hf, lines = _v10_fit_headline(draw, headline, maxw, max_height=275)
    heights = [draw.textbbox((0,0), line, font=hf, stroke_width=3)[3] for line in lines]
    total_h = sum(heights) + 12 * max(0, len(lines)-1)
    start_y = max(y1 + 72, int((y1 + y2 - total_h) / 2) - 12)
    if start_y + total_h > y2 - 95:
        start_y = y2 - 95 - total_h
    y = start_y
    for idx, line in enumerate(lines):
        fill = (255,255,255,255) if idx < len(lines)-1 else accent
        draw.text((tx, y), line, font=hf, fill=fill, stroke_width=5, stroke_fill=(0,0,0,235))
        y += heights[idx] + 12

    sub = _clean_text(subline).upper()[:30]
    if sub:
        sf = _v6_thumb_font(24, heavy=False)
        draw.text((tx, min(y + 10, y2 - 50)), sub, font=sf, fill=(242,246,252,245), stroke_width=2, stroke_fill=(0,0,0,205))
    line_y = min(y2 - 26, max(y1 + 70, y + 8))
    draw.line((tx, line_y, min(tx + min(190, maxw), x2), line_y), fill=accent2, width=4)


def _v10_render(background: Image.Image, out: Path, headline: str, subline: str, label: str, brief, variant: int) -> dict:
    from .thumbnail_director import detect_text_zone
    bg = _fit_background(background).convert("RGB")
    bg = ImageEnhance.Contrast(bg).enhance(1.16)
    bg = ImageEnhance.Color(bg).enhance(1.12)
    bg = ImageEnhance.Sharpness(bg).enhance(1.16)
    canvas = bg.convert("RGBA")
    zone, box, left_score, right_score = detect_text_zone(bg)
    _v10_apply_text_zone(canvas, zone, box, headline, subline, label, variant)
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(out, "JPEG", quality=97, optimize=True, progressive=True)
    return {"text_zone": zone, "zone_box": list(box), "left_complexity": round(left_score, 2), "right_complexity": round(right_score, 2)}


def _v10_thumbnail_score(path: Path, zone_meta: dict) -> float:
    from PIL import ImageStat
    with Image.open(path) as im:
        small = im.convert("RGB").resize((320, 180))
        stat = ImageStat.Stat(small)
        contrast = sum(stat.stddev) / 3.0
        mean = sum(stat.mean) / 3.0
        brightness = max(0.0, 1.0 - abs(mean - 128.0) / 128.0)
        edges = small.convert("L").filter(ImageFilter.FIND_EDGES)
        edge_energy = ImageStat.Stat(edges).mean[0]
        quiet = min(zone_meta.get("left_complexity", 100), zone_meta.get("right_complexity", 100))
        return round(contrast * 1.9 + brightness * 25.0 + edge_energy * 0.55 + max(0.0, 75.0 - quiet) * 0.9, 2)


def create_custom_thumbnail(video_path: Path, out_path: Path, challenge_time: float, question: str, label: str,
                            background_path: Path | None = None, topic: str = "", variants: int | None = None,
                            subline: str = "", visual_prompt: str = "") -> Path:
    """V10: creative-director thumbnail factory.

    Five materially different art concepts are generated. AI makes only the
    artwork; typography is composited after measuring the generated image.
    """
    from .thumbnail_director import build_brief, build_prompt, headline as director_headline, subline as director_subline, brief_manifest

    count = max(5, int(variants or os.getenv("THUMBNAIL_VARIANTS", "5")))
    final_headline = director_headline(question, topic)
    final_subline = director_subline(subline, topic)
    variant_dir = out_path.parent / "thumbnail_variants"
    variant_dir.mkdir(parents=True, exist_ok=True)
    seed_base = int(hashlib.sha1(f"v10|{topic}|{final_headline}|{final_subline}|{label}".encode("utf-8")).hexdigest()[:10], 16)
    clean = _load_clean_background(video_path, background_path, challenge_time)
    candidates: list[tuple[Path, dict, dict]] = []

    for i in range(count):
        brief = build_brief(topic or label, final_headline, final_subline, i)
        prompt = build_prompt(brief)
        if visual_prompt and len(_clean_text(visual_prompt)) > 45:
            prompt += f" Additional concept cue: {_clean_text(visual_prompt)[:500]}"
        seed = seed_base + i * 7919
        try:
            ai_img = _request_ai_background(prompt, seed)
        except Exception as exc:
            print(f"[thumbnail-v10] AI candidate {i+1} failed: {exc}")
            ai_img = None
        bg = ai_img if ai_img is not None else clean
        path = variant_dir / f"v10_{i+1:02d}_{['metaphor','confrontation','journey','macro','editorial'][i % 5]}.jpg"
        zone_meta = _v10_render(bg, path, final_headline, final_subline, label, brief, i)
        score = _v10_thumbnail_score(path, zone_meta)
        candidates.append((path, zone_meta, {"brief": brief_manifest(brief), "score": score}))

    ranked = sorted(candidates, key=lambda item: item[2]["score"], reverse=True)
    if not ranked:
        raise RuntimeError("V10 thumbnail director produced no candidates")
    best, best_zone, _ = ranked[0]
    Image.open(best).convert("RGB").save(out_path, "JPEG", quality=97, optimize=True, progressive=True)
    manifest = {
        "engine": "v10_creative_director",
        "headline": final_headline,
        "subline": final_subline,
        "selected": best.name,
        "variants": [p.name for p, _, _ in ranked],
        "scores": {p.name: m["score"] for p, _, m in candidates},
        "composition": {p.name: z for p, z, _ in candidates},
        "creative_briefs": {p.name: m["brief"] for p, _, m in candidates},
        "canvas": [THUMBNAIL_W, THUMBNAIL_H],
        "model": os.getenv("CLOUDFLARE_THUMBNAIL_MODEL", "@cf/black-forest-labs/flux-2-klein-4b"),
        "image_first": True,
        "text_generated_after_art": True,
    }
    (variant_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[thumbnail-v10] selected={best.name}; variants={len(ranked)}; text_zone={best_zone['text_zone']}")
    return out_path

# ═════════════════════════════════════════════════════════════════════════════
# THUMBNAIL-ONLY PATCH — V11 / creator thumbnail, no HUD/card treatment
# ═════════════════════════════════════════════════════════════════════════════
# This override intentionally changes ONLY the thumbnail factory.  Video scenes,
# scripts, TTS, SEO, topic selection and rendering are untouched.

_V11_BAD_HEADLINE = re.compile(
    r"^(?:WHICH|WHAT|WHY|HOW|CAN|DOES|DID|WHERE|WHO|WHEN)\b|\?|\b(?:QUICK TEST|THINK FAST|REVEAL|THE TRICK|KEY DIFFERENCE|KEY CONCEPT|THE CONCEPT|WORKED EXAMPLE|EXAM CLUE|CAN YOU)\b",
    re.I,
)

_V11_EXAM_PREFIX = re.compile(
    r"^(?:IBPS|SBI|RBI|UPSC|SSC|GATE|NABARD|PFRDA|RRB)\s*(?:SO|PO|CLERK|GRADE\s*A|GRADE\s*B)?\s*(?:IT)?\s*[:|\-–—]?\s*",
    re.I,
)


def _v11_core_topic(topic: str, fallback: str = "") -> str:
    raw = _clean_text(topic or fallback)
    raw = _V11_EXAM_PREFIX.sub("", raw).strip(" -:|")
    if ":" in raw:
        raw = raw.split(":", 1)[0].strip()
    raw = re.sub(r"\b(?:explained|concept|trick|question|question\s*\&\s*answer|difference)\b", "", raw, flags=re.I)
    raw = re.sub(r"\s{2,}", " ", raw).strip(" -:|,")
    return raw


def _v11_compact_words(text: str, max_words: int = 4, max_chars: int = 30) -> str:
    words = re.findall(r"[A-Za-z0-9]+(?:[-/][A-Za-z0-9]+)*", _clean_text(text))
    if len(words) > max_words:
        words = words[:max_words]
    value = " ".join(words).upper()
    return value[:max_chars].rstrip(" -:|,;")


def _v11_symbolic_copy(text: str, max_chars: int = 32) -> str:
    value = _clean_text(text).upper()
    value = re.sub(r"\s*→\s*", " → ", value)
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) > max_chars:
        value = value[:max_chars].rsplit(" ", 1)[0].rstrip(" -:/")
    return value


def _v11_thumbnail_copy(topic: str, question: str, subline: str) -> tuple[str, str]:
    """Create short creator-style copy; never a sentence/question on the thumbnail."""
    low = _clean_text(topic).lower()
    mappings = (
        (r"\bcrr\b.*\bslr\b", "CRR VS SLR", "CASH VS SECURITIES"),
        (r"\bcrr\b", "CRR", "CASH RESERVE"),
        (r"\bslr\b", "SLR", "LIQUID ASSETS"),
        (r"\bsdf\b.*\breverse repo\b", "SDF VS REVERSE REPO", "LIQUIDITY DIRECTION"),
        (r"\bifsc\b", "IFSC CODE", "11 CHARACTERS"),
        (r"\bneft\b.*\brtgs\b.*\bimps\b", "NEFT VS RTGS", "IMPS + PAYMENT SPEED"),
        (r"letter.*shift|coding.*decoding", "LETTER SHIFT", "THE SHIFT RULE"),
        (r"feynman", "FEYNMAN TECHNIQUE", "LEARN BY EXPLAINING"),
        (r"normalization|1nf.*2nf.*3nf", "NORMALIZATION", "1NF → 2NF → 3NF"),
        (r"tcp.*3-way|3-way.*handshake|syn.*syn-ack|syn-ack.*ack", "3-WAY HANDSHAKE", "SYN → SYN-ACK → ACK"),
        (r"tcp.*udp", "TCP VS UDP", "RELIABLE VS FAST"),
        (r"machine input.*output", "MACHINE INPUT", "FOLLOW THE PATTERN"),
        (r"goosebumps|music.*brain", "GOOSEBUMPS", "THE BRAIN REACTION"),
        (r"ransomware", "RANSOMWARE", "BANKING DEFENSE"),
        (r"deadlock.*coffman", "DEADLOCK", "4 COFFMAN CONDITIONS"),
        (r"group by.*having", "GROUP BY + HAVING", "FILTER AT THE RIGHT STAGE"),
        (r"basel iii", "BASEL III", "CAPITAL BUFFER"),
        (r"percentage change", "PERCENTAGE CHANGE", "FAST SAFE METHOD"),
        (r"successive.*profit|profit.*loss", "PROFIT & LOSS", "SUCCESSIVE CHANGE"),
        (r"banker algorithm", "BANKER'S ALGORITHM", "SAFE STATE"),
    )
    for pattern, head, sub in mappings:
        if re.search(pattern, low):
            return head, sub

    candidate = _v11_compact_words(question, 4, 30)
    if _V11_BAD_HEADLINE.search(candidate) or len(candidate.split()) < 2:
        candidate = _v11_compact_words(_v11_core_topic(topic, question), 4, 30)
    if not candidate:
        candidate = "KEY CONCEPT"

    sub = _v11_symbolic_copy(subline, 32)
    if not sub:
        sub = _v11_compact_words(subline, 4, 28)
    if not sub or _V11_BAD_HEADLINE.search(sub):
        tail = _clean_text(topic).split(":", 1)[1] if ":" in _clean_text(topic) else ""
        sub = _v11_compact_words(tail, 4, 28)
    if not sub:
        sub = "EXAM READY"
    return candidate, sub


def _v11_visual_prompt(topic: str, headline: str, subline: str, variant: int) -> str:
    """Ask the image model for a single editorial hero, not a poster."""
    core = _v11_core_topic(topic, headline)
    visual_by_topic = (
        (r"crr.*slr", "a bank reserve vault on one side and government-security assets on the other, visibly separated by a decisive divide"),
        (r"ifsc", "a bank transfer travelling through a precise international payment-routing network, one destination clearly illuminated"),
        (r"letter|coding|decoding", "large physical letter tiles shifting through a mechanical sequence with one transformed result at the end"),
        (r"tcp.*3-way|3-way.*handshake|syn.*syn-ack", "three realistic network endpoints connected by a clear packet path, with one luminous handshake packet travelling from the client to the server and a return acknowledgement path"),
        (r"tcp|udp|network|osi|arp", "a data packet moving through a realistic network of routers and servers, with a clear route and endpoint"),
        (r"deadlock|banker|algorithm|database|sql|normalization", "a sophisticated computer-system mechanism with connected data blocks and one clear cause-to-result transformation"),
        (r"physics|chemistry|biology|brain|goosebumps|science", "one striking scientific mechanism shown as a premium macro/cinematic physical process"),
        (r"percentage|profit|loss|ratio|average|simplification|arithmetic", "a clean physical calculation metaphor using coins, blocks or measured quantities transforming from input to result"),
        (r"history|polity|constitution|geography|economy|rbi|bank|finance", "one authentic object or environment that physically represents the exact concept, with cinematic depth"),
    )
    scene = "one unmistakable physical metaphor for the exact concept"
    for pattern, value in visual_by_topic:
        if re.search(pattern, core, re.I):
            scene = value
            break
    layouts = (
        "hero weighted to the RIGHT 58-65%, clean darker negative space on the LEFT",
        "hero weighted to the RIGHT 62%, strong diagonal depth toward the LEFT text area",
        "hero on the RIGHT with one secondary supporting object near center, LEFT remains visually quiet",
        "tight cinematic hero on the RIGHT, shallow depth of field, clean LEFT atmosphere",
        "two concept elements on the RIGHT separated by a clear physical divide, LEFT kept simple",
    )
    return (
        "Create original premium YouTube thumbnail HERO ARTWORK for an Indian competitive-exam education channel. "
        f"Exact concept: {core}. Thumbnail idea: {headline}. Clarifier: {subline}. "
        f"Visual metaphor: {scene}. Composition: {layouts[variant % len(layouts)]}. "
        "The image must communicate the concept before typography is added. Use one dominant subject, large readable silhouette, "
        "strong focal lighting, cinematic perspective, realistic materials, layered depth, premium commercial photography/3D realism, "
        "high contrast and saturated but disciplined color. Avoid generic classrooms, generic vaults, stock photos, dashboards, "
        "flat infographic cards, UI panels, random icons, decorative neon wallpaper, collage layouts and tiny details. "
        "NO WORDS, NO LETTERS, NO NUMBERS, NO LOGOS, NO WATERMARKS, NO BORDERS, NO TYPOGRAPHY. Landscape 16:9."
    )


def _v11_render(background: Image.Image, out: Path, headline: str, subline: str, label: str, variant: int) -> dict:
    """Minimal, mobile-first thumbnail: image dominates; copy is short and huge."""
    from .thumbnail_director import detect_text_zone

    bg = _fit_background(background).convert("RGB")
    bg = ImageEnhance.Contrast(bg).enhance(1.20)
    bg = ImageEnhance.Color(bg).enhance(1.16)
    bg = ImageEnhance.Sharpness(bg).enhance(1.10)
    canvas = bg.convert("RGBA")
    zone, box, left_score, right_score = detect_text_zone(bg)

    # Prefer the quiet half, but never cover the hero with a fixed black card.
    draw = ImageDraw.Draw(canvas)
    x1, y1, x2, y2 = box
    if zone == "left":
        tx, maxw = 55, 570
        # very soft left-to-right readability gradient
        grad = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        gd = ImageDraw.Draw(grad)
        for x in range(0, 690):
            t = x / 689
            gd.line((x, 0, x, 720), fill=(0, 0, 0, int(150 * (1 - t) ** 2.0)))
        canvas.alpha_composite(grad)
    else:
        tx, maxw = 675, 540
        grad = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        gd = ImageDraw.Draw(grad)
        for x in range(590, 1280):
            t = (x - 590) / 689
            gd.line((x, 0, x, 720), fill=(0, 0, 0, int(150 * t ** 2.0)))
        canvas.alpha_composite(grad)

    draw = ImageDraw.Draw(canvas)
    accent = _V6_ACCENTS[variant % len(_V6_ACCENTS)] + (255,)
    accent2 = _V6_ACCENTS[(variant + 1) % len(_V6_ACCENTS)] + (255,)

    # Tiny, unobtrusive exam tag — no boxed UI.
    tag = _clean_text(label).upper()[:18]
    if tag:
        tag_font = _v6_thumb_font(20, heavy=True)
        draw.text((tx, 38), tag, font=tag_font, fill=(255, 255, 255, 230), stroke_width=2, stroke_fill=(0, 0, 0, 170))
        draw.line((tx, 69, min(tx + 130, tx + maxw), 69), fill=accent, width=5)

    # Main copy: 2–4 words, enormous, with only the last line accented.
    clean_head = _v11_compact_words(headline, 4, 30) or "KEY CONCEPT"
    hf, lines = _v8_fit_text(draw, clean_head, maxw, max_lines=2, start=122, minimum=58)
    heights = [draw.textbbox((0, 0), line, font=hf, stroke_width=3)[3] for line in lines]
    total = sum(heights) + 8 * max(0, len(lines) - 1)
    y = max(120, min(230, int((720 - total) * 0.48)))
    for idx, line in enumerate(lines):
        fill = (255, 255, 255, 255) if idx < len(lines) - 1 else accent
        draw.text((tx, y), line, font=hf, fill=fill, stroke_width=6, stroke_fill=(0, 0, 0, 235))
        y += heights[idx] + 8

    clean_sub = _v11_symbolic_copy(subline, 32) or _v11_compact_words(subline, 4, 28)
    if clean_sub:
        sf = _v6_thumb_font(25, heavy=True)
        # A single short clarifier, not a sentence.
        draw.text((tx, y + 14), clean_sub, font=sf, fill=(245, 248, 252, 245), stroke_width=3, stroke_fill=(0, 0, 0, 210))

    # One visual accent only; no giant question marks, fake timers or game UI.
    if variant % 3 == 0:
        draw.line((tx, 640, min(tx + 185, tx + maxw), 640), fill=accent2, width=5)
    elif variant % 3 == 1:
        draw.arc((tx + maxw - 115, 545, tx + maxw + 30, 690), 205, 320, fill=accent2, width=6)
    else:
        draw.ellipse((tx + maxw - 65, 595, tx + maxw - 25, 635), fill=accent2)

    draw.text((tx, 675), "EXAMCRACKER", font=_v6_thumb_font(15, heavy=False), fill=(240, 244, 250, 150))
    canvas.convert("RGB").save(out, "JPEG", quality=97, optimize=True, progressive=True)
    return {
        "text_zone": zone,
        "zone_box": list(box),
        "left_complexity": round(left_score, 2),
        "right_complexity": round(right_score, 2),
    }


def _v11_thumbnail_score(path: Path, zone_meta: dict, headline: str = "", subline: str = "") -> float:
    """Deterministic 25-signal-style packaging score for mobile thumbnail selection.

    This is a presentation heuristic, not a prediction of YouTube CTR. It
    rewards legibility, contrast, negative space, balanced visual weight and
    disciplined copy while penalizing clutter-like compositions.
    """
    from PIL import ImageStat
    with Image.open(path) as im:
        small = im.convert("RGB").resize((320, 180))
        stat = ImageStat.Stat(small)
        mean = sum(stat.mean) / 3.0
        contrast = sum(stat.stddev) / 3.0
        brightness = max(0.0, 1.0 - abs(mean - 122.0) / 122.0)
        edges = small.convert("L").filter(ImageFilter.FIND_EDGES)
        edge_energy = ImageStat.Stat(edges).mean[0]
        left = ImageStat.Stat(small.crop((0, 0, 150, 180)))
        right = ImageStat.Stat(small.crop((170, 0, 320, 180)))
        left_var = sum(left.stddev) / 3.0
        right_var = sum(right.stddev) / 3.0
        balance = min(left_var, right_var)
        quiet = min(zone_meta.get("left_complexity", 100), zone_meta.get("right_complexity", 100))
        zone_gap = abs(zone_meta.get("left_complexity", 100) - zone_meta.get("right_complexity", 100))
        headline_words = len(re.findall(r"[A-Za-z0-9]+(?:[-/][A-Za-z0-9]+)*", headline or ""))
        sub_words = len(re.findall(r"[A-Za-z0-9]+(?:[-/][A-Za-z0-9]+)*", subline or ""))
        copy_penalty = 0.0
        if not 2 <= headline_words <= 4:
            copy_penalty += 24.0
        if len(_clean_text(headline)) > 30:
            copy_penalty += 18.0
        if sub_words > 6:
            copy_penalty += 10.0
        if re.search(r"[?]", headline or ""):
            copy_penalty += 12.0
        if re.search(r"\b(QUICK TEST|THINK FAST|REVEAL|KEY DIFFERENCE|WORKED EXAMPLE|EXAM CLUE)\b", headline or "", re.I):
            copy_penalty += 20.0
        text_zone_score = max(0.0, 100.0 - quiet) * 1.25
        subject_zone_score = min(46.0, zone_gap * 0.55)
        return round(
            contrast * 2.0
            + brightness * 28.0
            + edge_energy * 0.50
            + balance * 0.48
            + text_zone_score
            + subject_zone_score
            - copy_penalty,
            2,
        )


def create_custom_thumbnail(video_path: Path, out_path: Path, challenge_time: float, question: str, label: str,
                            background_path: Path | None = None, topic: str = "", variants: int | None = None,
                            subline: str = "", visual_prompt: str = "") -> Path:
    """V11 thumbnail-only upgrade. Nothing outside thumbnail generation is changed."""
    count = max(5, int(variants or os.getenv("THUMBNAIL_VARIANTS", "5")))
    headline, secondary = _v11_thumbnail_copy(topic, question, subline)
    variant_dir = out_path.parent / "thumbnail_variants"
    variant_dir.mkdir(parents=True, exist_ok=True)
    seed_base = int(hashlib.sha1(f"v11|{topic}|{headline}|{secondary}|{label}".encode("utf-8")).hexdigest()[:10], 16)
    clean = _load_clean_background(video_path, background_path, challenge_time)
    candidates: list[tuple[Path, dict, float]] = []

    for i in range(count):
        prompt = _v11_visual_prompt(topic or label, headline, secondary, i)
        if visual_prompt and len(_clean_text(visual_prompt)) > 45:
            prompt += f" Exact visual cue from the content brief: {_clean_text(visual_prompt)[:450]}."
        seed = seed_base + i * 7919
        try:
            ai_img = _request_ai_background(prompt, seed)
        except Exception as exc:
            print(f"[thumbnail-v11] AI candidate {i + 1} failed: {exc}")
            ai_img = None
        if ai_img is not None:
            bg = ai_img
            bg_source = "cloudflare"
        else:
            # Do not fall back to a random video frame: use a concept-specific
            # designed fallback so the thumbnail remains intentional during quota exhaustion.
            bg = _v11_procedural_hero(topic or label, i)
            bg_source = "procedural_concept"
        path = variant_dir / f"v11_{i + 1:02d}.jpg"
        meta = _v11_render(bg, path, headline, secondary, label, i)
        score = _v11_thumbnail_score(path, meta, headline, secondary)
        meta["background_source"] = bg_source
        meta["hit_rate_score"] = score
        candidates.append((path, meta, score))

    ranked = sorted(candidates, key=lambda item: item[2], reverse=True)
    if not ranked:
        raise RuntimeError("V11 thumbnail engine produced no candidates")
    best, best_meta, best_score = ranked[0]
    Image.open(best).convert("RGB").save(out_path, "JPEG", quality=97, optimize=True, progressive=True)
    manifest = {
        "engine": "v10_creative_director",
        "thumbnail_patch": "v17_hit_rate_v2_thumbnail_only",
        "hit_rate_program": "25-point-thumbnail-hit-rate-program",
        "headline": headline,
        "subline": secondary,
        "selected": best.name,
        "variants": [p.name for p, _, _ in ranked],
        "scores": {p.name: score for p, _, score in candidates},
        "composition": {p.name: meta for p, meta, _ in candidates},
        "creative_briefs": {p.name: {"thumbnail_patch": "v11_thumbnail_only", "variant": i + 1} for i, (p, _, _) in enumerate(candidates)},
        "canvas": [THUMBNAIL_W, THUMBNAIL_H],
        "ai_provider": os.getenv("CLOUDFLARE_THUMBNAIL_MODEL", "@cf/black-forest-labs/flux-2-klein-4b"),
        "copy_rule": "2-4 word concept headline + short mechanism clarifier",
        "api_failover": "CLOUDFLARE_ACCOUNT_ID[_2.._4] + CLOUDFLARE_API_TOKEN[_2.._4]",
    }
    (variant_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[thumbnail-v11] selected={best.name}; score={best_score}; headline={headline!r}; subline={secondary!r}")
    return out_path
