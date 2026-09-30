"""V10 thumbnail art director.

Turns a topic into a visual concept before image generation.  The diffusion model
creates only the artwork; Pillow places the final copy after analyzing the actual
image for a quiet text-safe zone.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from PIL import Image, ImageFilter, ImageStat

@dataclass(frozen=True)
class CreativeBrief:
    concept: str
    visual_metaphor: str
    focal_subject: str
    action: str
    composition: str
    style: str
    palette: str
    text_zone: str
    headline: str
    subline: str

STYLE_RULES = (
    (re.compile(r"\b(rbi|bank|banking|repo|crr|slr|npa|neft|rtgs|imps|money|deposit|liquidity|finance)\b", re.I),
     "premium financial advertising, cinematic fintech realism, polished glass/metal materials, believable money and banking objects"),
    (re.compile(r"\b(sql|database|tcp|udp|http|api|os|deadlock|code|program|algorithm|data structure|network|computer)\b", re.I),
     "premium futuristic technical editorial, realistic hardware and luminous data structures, sophisticated engineering visualization"),
    (re.compile(r"\b(history|empire|war|ancient|medieval|dynasty|constitution|polity|parliament|governance)\b", re.I),
     "cinematic documentary reconstruction, authentic period objects and architecture, dramatic natural light, premium historical editorial"),
    (re.compile(r"\b(geography|river|mountain|climate|monsoon|map|earth|ocean|soil)\b", re.I),
     "premium 3D geographic visualization, realistic terrain, satellite/cartographic depth, cinematic environmental lighting"),
    (re.compile(r"\b(physics|chemistry|biology|cell|molecule|atom|force|energy|human body|science)\b", re.I),
     "high-end science documentary visualization, realistic laboratory/scientific objects, macro detail and controlled cinematic light"),
)

CONCEPTS = (
    ("visual_metaphor", "one unmistakable physical metaphor for the concept", "the core concept transformed into one large cinematic object", "the object visibly moves or changes state"),
    ("confrontation", "two exact concepts physically competing or separating", "the two concepts as distinct hero objects", "a decisive split, collision, or fork between them"),
    ("journey", "a process shown as a dramatic route from input to outcome", "the input object travelling through a clear mechanism", "motion through a route with a visible destination"),
    ("macro", "an extreme close-up revealing the mechanism people usually miss", "one important physical detail or component", "a reveal from hidden/internal state to visible result"),
    ("editorial_human", "a human reaction anchored to the exact concept rather than generic education", "a realistic Indian learner plus one exact concept object", "the person reacting to the mechanism or result"),
)


def clean_words(text: str, limit: int) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    return s[:limit].rstrip(" -:;,.!? ")


def headline(text: str, topic: str) -> str:
    banned = re.compile(r"\b(a\s*(?:or|vs\.?|versus)\s*b|quick test|think fast|countdown|stop|reveal|the trick|did you get it|boss fight|5 seconds)\b", re.I)
    h = clean_words(text, 42)
    if banned.search(h) or len(h.split()) > 5 or len(h.split()) < 1:
        # Prefer a concept phrase rather than a quiz/game slogan.
        base = re.split(r"[:—|]", clean_words(topic, 54))[0].strip()
        words = base.split()[:4]
        h = " ".join(words) if words else "THE KEY DIFFERENCE"
    return h.upper()


def subline(text: str, topic: str) -> str:
    s = clean_words(text, 34)
    if not s:
        s = clean_words(re.split(r"[:—|]", topic)[0], 34)
    return s.upper()


def choose_style(topic: str) -> str:
    for pattern, style in STYLE_RULES:
        if pattern.search(topic):
            return style
    return "premium editorial concept art, realistic materials, cinematic commercial lighting, sophisticated creator-thumbnail finish"


def build_brief(topic: str, headline_text: str, subline_text: str, variant: int) -> CreativeBrief:
    kind, metaphor, focal, action = CONCEPTS[variant % len(CONCEPTS)]
    style = choose_style(topic)
    palettes = (
        "deep navy, electric cyan, warm gold, controlled red accent",
        "rich charcoal, white highlights, electric blue, one warm accent",
        "deep teal, luminous gold, clean white highlights, subtle crimson",
        "graphite, cobalt, warm amber, high-contrast white",
        "deep blue-black, premium skin tones where applicable, gold highlight, restrained cyan",
    )
    return CreativeBrief(
        concept=clean_words(topic, 90),
        visual_metaphor=metaphor,
        focal_subject=focal,
        action=action,
        composition=(
            "landscape 16:9; make the hero occupy roughly 55-65 percent of the frame; "
            "reserve 35-45 percent of the opposite side as visually quieter negative space; "
            "no important face, object, bright edge, or high-detail mechanism in the text zone"
        ),
        style=style,
        palette=palettes[variant % len(palettes)],
        text_zone="left" if variant % 2 == 0 else "right",
        headline=headline_text,
        subline=subline_text,
    )


def build_prompt(brief: CreativeBrief) -> str:
    return (
        "Create a premium, original YouTube thumbnail HERO ARTWORK. "
        f"Topic: {brief.concept}. Visual metaphor: {brief.visual_metaphor}. "
        f"Focal subject: {brief.focal_subject}. Action: {brief.action}. "
        f"Composition: {brief.composition}. Style: {brief.style}. Palette: {brief.palette}. "
        "Make the visual understandable without any text: one dominant subject, one clear action, strong silhouette, "
        "layered foreground/midground/background, dramatic perspective, believable materials, crisp focal detail, "
        "controlled highlights, depth haze, rich but disciplined contrast, premium advertising finish. "
        "Do NOT create a lesson slide, stock-photo collage, UI dashboard, infographic panel, generic classroom, "
        "random neon wallpaper, fake chart, decorative symbols, or poster frame. "
        "NO WORDS, NO LETTERS, NO NUMBERS, NO LOGOS, NO WATERMARKS, NO CAPTIONS, NO LABELS, NO BORDERS, NO TYPOGRAPHY. Do NOT render any of them."
    )


def _region_score(img: Image.Image, box: tuple[int,int,int,int]) -> float:
    """Lower is quieter: edge energy + local variance + excessive saturation."""
    crop = img.crop(box).convert("RGB").resize((160, 90))
    gray = crop.convert("L")
    edge = ImageStat.Stat(gray.filter(ImageFilter.FIND_EDGES)).mean[0]
    stat = ImageStat.Stat(crop)
    variance = sum(stat.stddev) / 3.0
    mean = sum(stat.mean) / 3.0
    saturation_proxy = max(stat.mean) - min(stat.mean)
    # Very bright regions are also poor for white typography.
    brightness_penalty = max(0.0, mean - 165.0) * 0.45
    return edge * 1.2 + variance * 0.75 + saturation_proxy * 0.15 + brightness_penalty


def detect_text_zone(img: Image.Image) -> tuple[str, tuple[int,int,int,int], float, float]:
    """Find a real quiet zone from the generated artwork, not from a fixed template."""
    w, h = img.size
    margin = int(w * 0.04)
    candidates = {
        "left": (margin, margin, int(w * 0.43), h - margin),
        "right": (int(w * 0.57), margin, w - margin, h - margin),
    }
    scores = {name: _region_score(img, box) for name, box in candidates.items()}
    zone = min(scores, key=scores.get)
    return zone, candidates[zone], scores["left"], scores["right"]


def brief_manifest(brief: CreativeBrief) -> dict:
    return asdict(brief)
