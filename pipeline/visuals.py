"""Premium visual acquisition for educational Shorts.

Cloudflare FLUX.1 Schnell is the active AI image generator for scene visuals.
Pexels is a fallback for photographic subjects. Gemini image generation is retained
only for future opt-in; script/text generation may still use Gemini separately.
"""
from __future__ import annotations

import base64
import hashlib
import os
import random
import threading
import time
import urllib.parse
from pathlib import Path

import requests
from PIL import Image

from .config import WORK_DIR
from .subject_area import classify_subject_area, SUBJECT_AREA_IMAGE_SUFFIX
from .thumbnail_ai import cloudflare_configured, generate_cloudflare_background

POLLINATIONS = "https://image.pollinations.ai/prompt/{prompt}"  # legacy constant; not used by the active image path

# ─────────────────────────────────────────────────────────────────────────────
# VISUAL PROVIDER CIRCUIT BREAKER (V3)
# Tracks provider health across the entire run. If a provider returns 404/429/402,
# it is immediately tripped and skipped for all subsequent scenes.
# ─────────────────────────────────────────────────────────────────────────────
PROVIDER_STATE: dict[str, str] = {
    "cloudflare_image": "available",
    "gemini_image": "available",  # retained for future image-provider re-enable; disabled by default
    "pollinations": "disabled",    # retired from primary image generation
    "pexels": "available",         # stock fallback
}


def reset_provider_state() -> None:
    """Reset circuit breaker for a new video run if desired."""
    global PROVIDER_STATE
    PROVIDER_STATE = {
        "cloudflare_image": "available",
        "gemini_image": "available",
        "pollinations": "disabled",
        "pexels": "available",
    }


# Same fix as Edge-TTS: scenes now run concurrently (generate.py), and firing
# every scene's image request at Pollinations' free tier simultaneously is
# what was producing the near-total 429 "Too Many Requests" wall seen in
# production (every scene falling through to the Pexels fallback instead of
# actually using Pollinations). Capping concurrent Pollinations requests here
# lets the rest of the per-scene pipeline still run in parallel. Tune via
# POLLINATIONS_CONCURRENCY.
_POLLINATIONS_SEMAPHORE = threading.Semaphore(max(1, int(os.getenv("POLLINATIONS_CONCURRENCY", "2"))))

STYLE_SUFFIX = {
    "handwritten_notes": (
        ", premium handwritten study-notes aesthetic on textured off-white notebook paper, "
        "realistic ink and pencil strokes, hand-drawn diagrams, arrows, circles, underlines, "
        "selective short handwritten labels, varied page composition, subtle marker highlights, "
        "teacher-made revision sheet, tactile paper texture, intelligent visual hierarchy, "
        "vertical 9:16, no typed UI, no logos, no watermark"
    ),
    "text_gradient_ai": (
        ", premium cinematic editorial illustration, strong focal subject, "
        "dramatic but natural lighting, rich depth, high contrast, realistic materials, "
        "vertical 9:16, no text, no logos, no watermark"
    ),
    "mixed_stock_ai": (
        ", premium documentary photography, cinematic composition, realistic Indian context "
        "when relevant, shallow depth of field, natural skin/material detail, dramatic lighting, "
        "vertical 9:16, no text, no logos, no watermark"
    ),
    "ai_cinematic": (
        ", ultra-premium cinematic film still, photorealistic, sophisticated composition, "
        "strong foreground and background separation, volumetric lighting, realistic textures, "
        "deep depth, subtle filmic contrast, vertical 9:16, no text, no logos, no watermark"
    ),
    "educational_ai": (
        ", premium cinematic educational visualization, photorealistic 3D or editorial scientific "
        "illustration, one unmistakable focal subject, clear cause-and-effect composition, "
        "layered depth, bright directional key light, rich but natural color separation, realistic materials, "
        "crisp focal detail, subtle atmosphere, visually striking but accurate, vertical 9:16, no text, no logos, no watermark"
    ),
    "cinematic_hud": (
        ", premium cinematic concept art, sophisticated dark-to-bright gradient environment, "
        "single glowing focal element with realistic physical context, strong foreground-background separation, "
        "volumetric key light, subtle lens flare, hyperrealistic materials, rich depth, vertical 9:16, no text, no labels, no logos, no watermark"
    ),
}

GLOBAL_QUALITY = (
    " high-end YouTube Shorts visual, visually arresting first-frame composition, "
    "clean subject separation, professional color grading, realistic detail, "
    "no generic corporate stock-photo look"
)


_MIN_USABLE_SIDE = 200  # below this, treat as a broken/error-page image, not a small photo


def _valid_image(path: Path) -> bool:
    """Cheap sanity check: is this a real, minimally-sized image file at all
    (not an HTML error page or truncated download)? Exact target dimensions
    are enforced separately by `_normalize_image`, since Pollinations often
    ignores the requested width/height and returns an odd size (e.g. a
    731x1300 image for a 1080x1920 request) — that's still a perfectly good
    photo, just the wrong canvas, so it shouldn't be discarded here.
    """
    try:
        with Image.open(path) as img:
            width, height = img.size
            return (
                width >= _MIN_USABLE_SIDE
                and height >= _MIN_USABLE_SIDE
                and path.stat().st_size >= 20_000
            )
    except Exception:
        return False


def _normalize_image(path: Path, target_w: int, target_h: int) -> bool:
    """Resize/crop any downloaded image to exactly target_w x target_h.

    Pollinations frequently ignores our requested width/height and returns
    something else (e.g. 731x1300 instead of 1080x1920). Previously that got
    rejected outright as "bad dimensions", wasting retries and Gemini quota
    on images that were actually fine — and on the rare one that scraped
    past the old, looser size floor, ffmpeg's zoompan chain then had to
    upscale it ~2x, which looked soft/blurry in the final Short.

    Instead, always normalize to the exact target canvas here with a
    cover-crop (scale up to fill both dimensions, then center-crop), so the
    output is consistently full-resolution regardless of what the API
    returned, and ffmpeg never has to upscale a too-small source image.
    """
    try:
        with Image.open(path) as img:
            img = img.convert("RGB")
            src_w, src_h = img.size
            if src_w < _MIN_USABLE_SIDE or src_h < _MIN_USABLE_SIDE:
                return False  # too small/garbage to be worth upscaling further
            scale = max(target_w / src_w, target_h / src_h)
            new_w = max(target_w, round(src_w * scale))
            new_h = max(target_h, round(src_h * scale))
            img = img.resize((new_w, new_h), Image.LANCZOS)
            left = (new_w - target_w) // 2
            top = (new_h - target_h) // 2
            img = img.crop((left, top, left + target_w, top + target_h))
            img.save(path, "JPEG", quality=92)
        return True
    except Exception:
        return False


def _fetch_gemini_image(
    prompt: str,
    out_path: Path,
    api_key: str,
    width: int = 1080,
    height: int = 1920,
) -> bool:
    """Generate high-resolution 9:16 vertical AI image using Google Gemini API.

    Uses circuit breaker: if any call returns 429 (quota), marks 'cooldown'
    and skips for the entire run. If 404, marks 'unsupported'.
    Removed broken imagen-3.0-generate-002 endpoint.
    """
    if not api_key or not api_key.strip():
        return False

    if PROVIDER_STATE.get("gemini_image") != "available":
        return False

    clean_key = api_key.strip()
    clean_prompt = " ".join((prompt or "").split())
    if "9:16" not in clean_prompt.lower():
        clean_prompt += ", vertical 9:16 aspect ratio, cinematic lighting, 8k resolution"

    # Multimodal generateContent with responseModalities IMAGE
    candidate_models = ("gemini-2.0-flash-exp-image-generation", "gemini-2.5-flash-image")
    all_404 = True

    for model in candidate_models:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={clean_key}"
            payload = {
                "contents": [{"parts": [{"text": clean_prompt}]}],
                "generationConfig": {
                    "responseModalities": ["IMAGE"],
                },
            }
            r = requests.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json", "x-goog-api-key": clean_key},
                timeout=45,
            )
            if r.status_code == 200:
                data = r.json()
                for cand in data.get("candidates", []):
                    for part in cand.get("content", {}).get("parts", []):
                        inline = part.get("inlineData") or part.get("inline_data")
                        if inline and inline.get("data"):
                            raw_bytes = base64.b64decode(inline["data"])
                            out_path.write_bytes(raw_bytes)
                            if _valid_image(out_path) and _normalize_image(out_path, width, height):
                                print(f"[visuals] gemini: successfully generated image via {model}")
                                return True
            elif r.status_code == 429:
                print(f"[visuals] gemini: quota limit hit (429) -> tripping circuit breaker (cooldown for entire run)")
                PROVIDER_STATE["gemini_image"] = "cooldown"
                return False
            elif r.status_code == 404:
                continue
            else:
                all_404 = False
                print(f"[visuals] gemini {model} status {r.status_code}: {r.text[:120]}")
        except Exception as exc:
            print(f"[visuals] gemini {model} error: {exc}")

    if all_404:
        # If all experimental image models returned 404 on this API tier, trip circuit breaker
        print("[visuals] gemini: image models not accessible on this API key -> disabling for run")
        PROVIDER_STATE["gemini_image"] = "unsupported"

    return False


def _fetch_pollinations(
    prompt: str,
    out_path: Path,
    width: int = 1080,
    height: int = 1920,
    attempts: int = 2,
    api_key: str | None = None,
) -> bool:
    if PROVIDER_STATE.get("pollinations") != "available":
        return False
    encoded = urllib.parse.quote(prompt, safe="")
    url = POLLINATIONS.format(prompt=encoded)
    last_error: Exception | None = None

    headers: dict[str, str] = {}
    current_key = api_key.strip() if api_key and api_key.strip() else None
    if current_key:
        headers["Authorization"] = f"Bearer {current_key}"

    for attempt in range(1, attempts + 1):
        params: dict[str, Any] = {
            "width": width,
            "height": height,
            "nologo": "true",
            "model": "flux",
            "seed": random.randint(1, 2_000_000_000),
        }
        if current_key:
            params["key"] = current_key
        try:
            with _POLLINATIONS_SEMAPHORE:
                r = requests.get(url, params=params, headers=headers, timeout=45)
                r.raise_for_status()
            if len(r.content) < 20_000:
                raise RuntimeError(f"response too small ({len(r.content)} bytes) — likely an error page, not an image")
            out_path.write_bytes(r.content)
            if not _valid_image(out_path):
                raise RuntimeError("downloaded file failed image validation (bad dimensions/corrupt)")
            if not _normalize_image(out_path, width, height):
                raise RuntimeError("downloaded image could not be normalized to target canvas")
            return True
        except Exception as exc:
            last_error = exc
            out_path.unlink(missing_ok=True)
            print(f"[visuals] pollinations attempt {attempt}/{attempts} failed: {exc}")
            if "402" in str(exc) or "Payment Required" in str(exc) or "429" in str(exc):
                print(f"[visuals] pollinations: error ({exc}) -> tripping circuit breaker (disabled for run)")
                PROVIDER_STATE["pollinations"] = "disabled"
                return False
            if attempt < attempts:
                time.sleep(2)

    print(f"[visuals] pollinations exhausted all attempts: {last_error}")
    return False


# Track photo IDs used in current video to ensure 100% visual variety
_USED_PEXELS_IDS: set[int] = set()


def _extract_scene_pexels_query(image_prompt: str, subject_area: str = "default") -> str:
    """Extract a distinct, photographic search query tailored to THIS specific scene."""
    stops = {
        "a", "an", "the", "in", "on", "at", "by", "with", "and", "or", "of", "to", "from",
        "cinematic", "photorealistic", "ultra-detailed", "vertical", "9:16", "lighting",
        "dark", "concept", "art", "glowing", "focal", "element", "volumetric", "light",
        "no", "text", "labels", "ultra-striking", "hook", "visual", "close-up", "shot",
        "view", "background", "showing", "scene", "illustration", "image"
    }
    words = [w.strip(".,;:\"'!?()[]{}") for w in (image_prompt or "").split()]
    meaningful = [w for w in words if len(w) > 2 and w.lower() not in stops]
    if len(meaningful) >= 2:
        return f"dark {' '.join(meaningful[:3])}"
    return _DARK_PEXELS_FALLBACK.get(subject_area, "dark abstract technology")


def _fetch_pexels(
    query: str,
    out_path: Path,
    api_key: str,
    width: int = 1080,
    height: int = 1920,
    scene_index: int = 0,
) -> bool:
    try:
        r = requests.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": api_key},
            params={
                "query": query,
                "orientation": "portrait",
                "per_page": 15,
                "size": "large",
            },
            timeout=45,
        )
        r.raise_for_status()
        photos = r.json().get("photos", [])
        if not photos:
            print(f"[visuals] pexels returned 0 results for query {query!r}")
            return False

        # Pick photo not yet used in this Short to guarantee visual variety across scenes
        chosen = None
        for p in photos:
            pid = p.get("id")
            if pid and pid not in _USED_PEXELS_IDS:
                chosen = p
                _USED_PEXELS_IDS.add(pid)
                break
        if not chosen:
            chosen = photos[scene_index % len(photos)]

        src = chosen.get("src", {}).get("large2x") or chosen.get("src", {}).get("original") or chosen.get("src", {}).get("large")
        if not src:
            return False
        img = requests.get(src, timeout=90)
        img.raise_for_status()
        out_path.write_bytes(img.content)
        if _valid_image(out_path) and _normalize_image(out_path, width, height):
            return True
        out_path.unlink(missing_ok=True)
        return False
    except Exception as exc:
        out_path.unlink(missing_ok=True)
        print(f"[visuals] pexels failed for query {query!r}: {exc}")
        return False


def _premium_prompt(image_prompt: str, visual_style: str, subject_area: str = "default") -> str:
    base = " ".join((image_prompt or "").split())
    # Very long prompts can make free image APIs time out or silently reject
    # the request. Cap it defensively — the schema already asks the LLM for
    # 20-45 words, so this only trims runaway outliers.
    if len(base) > 600:
        base = base[:600].rsplit(" ", 1)[0]
    suffix = STYLE_SUFFIX.get(visual_style, STYLE_SUFFIX["educational_ai"])
    # Layer 1: per-subject-area visual identity (satellite drama for
    # geography, aged manuscript for history, neon lab for science, clean
    # editorial for economy) layered ON TOP of the niche's base style so
    # every video in a niche doesn't share one visual identity regardless
    # of what it's actually about.
    area_suffix = SUBJECT_AREA_IMAGE_SUFFIX.get(subject_area, "") if visual_style != "handwritten_notes" else ""
    composition_hint = (
        " Build a distinct composition for this scene; do not reuse a generic template. "
        "The visual must look hand-created for this exact explanation, with the main mechanism "
        "obvious at first glance and the important relationship drawn rather than merely written."
    )
    text_note = (
        " Do not replace the concept with unrelated decorative imagery."
        if visual_style == "handwritten_notes"
        else " Do not replace the concept with unrelated decorative imagery. Do not render any words, "
             "letters, labels or numbers in the image — any on-screen text is added separately."
    )
    return (
        "Create this exact visual concept: "
        + base
        + composition_hint
        + GLOBAL_QUALITY
        + suffix
        + area_suffix
        + text_note
    )


def _pollinations_prompt(image_prompt: str, visual_style: str) -> str:
    """Build a COMPACT prompt for Pollinations free tier.

    The free Pollinations API rejects overly-long URL-encoded prompts with
    402 Payment Required. `_premium_prompt()` concatenates ~190+ words of
    style directives that balloon the URL well past the limit. This function
    keeps only the LLM's actual concept + a minimal style nudge, capped at
    250 chars total — short enough to always succeed.
    """
    base = " ".join((image_prompt or "").split())
    if len(base) > 140:
        base = base[:140].rsplit(" ", 1)[0]

    _COMPACT_SUFFIX = {
        "cinematic_hud": ", dark cinematic concept art, midnight background, glowing focal element, volumetric light, 9:16, no text no labels",
        "educational_ai": ", cinematic educational illustration, dramatic lighting, 9:16, no text",
        "handwritten_notes": ", handwritten study notes on textured paper, ink diagrams, 9:16",
        "text_gradient_ai": ", cinematic editorial illustration, dramatic lighting, 9:16, no text",
        "mixed_stock_ai": ", documentary photography, cinematic, 9:16, no text",
        "ai_cinematic": ", ultra-cinematic film still, deep depth of field, 9:16, no text",
    }
    suffix = _COMPACT_SUFFIX.get(visual_style, ", cinematic illustration, 9:16, no text")
    return base + suffix


# Dark-themed Pexels fallback queries by subject area — used when Cloudflare
# generation is unavailable and we fall through to stock imagery. Generic bright stock photos
# ("education", "concept") look terrible under a cinematic_hud dark scrim;
# these queries are curated to return images that already match the dark
# dramatic aesthetic.
_DARK_PEXELS_FALLBACK: dict[str, str] = {
    "geography": "dark aerial landscape night",
    "history": "dark ancient monument dramatic",
    "science": "dark laboratory neon glow",
    "economy": "dark bank vault dramatic lighting",
    "psychology": "dark brain neural abstract",
    "india": "dark india monument night",
    "default": "dark abstract technology concept",
}


# ─────────────────────────────────────────────────────────────────────────────
# Text-card visuals (visual_style == "text_card")
#
# Kept as a deterministic fallback for factual/diagram-heavy scenes when an
# external image provider is unavailable.
#
# Channel analytics showed the videos that actually get views are exam-topic
# text cards (the facts are readable on screen), while AI-image scenes can't
# show the facts at all (images carry no text) and kept collapsing into the
# same generic statue/brain picture. Cards are drawn locally with Pillow, so
# they need no Pollinations/Pexels call: no rate limits, no off-topic stock,
# and the scene is ready instantly.
#
# Layout keeps the middle band (~45-75%) free for the karaoke captions and the
# keyword label that render.py draws on top.
# ─────────────────────────────────────────────────────────────────────────────
_CARD_PALETTES = [
    ((8, 20, 44), (14, 52, 96), (0, 209, 255)),     # navy  / cyan
    ((30, 12, 52), (72, 28, 110), (255, 190, 60)),  # plum  / amber
    ((6, 36, 34), (10, 84, 72), (140, 255, 120)),   # teal  / lime
    ((44, 14, 22), (100, 26, 44), (255, 120, 160)), # wine  / pink
    ((14, 22, 36), (36, 56, 92), (255, 150, 60)),   # slate / orange
]


def _card_font(size: int, bold: bool = True):
    from PIL import ImageFont
    import glob
    names = (["Inter*Bold*", "Inter-Bold*", "InterVariable*"] if bold else ["Inter*Regular*", "Inter-Regular*", "InterVariable*"])
    candidates: list[str] = []
    for n in names:
        candidates += glob.glob(f"/usr/share/fonts/**/{n}.*tf", recursive=True)
    candidates += [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for c in candidates:
        try:
            return ImageFont.truetype(c, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _wrap_px(draw, text: str, font, max_w: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


_CURIOUS_BADGES = [
    "⚡ 3-SEC SHORTCUT",
    "💡 THE CORE TRICK",
    "⚠️ EXAM TRAP TO AVOID",
    "🎯 100% REPEATED RULE",
    "✍️ COMMENT YOUR ANSWER",
]


def _render_text_card(
    out_path: Path, scene_index: int, headline: str, points: list[str], tag: str,
    width: int = 1080, height: int = 1920,
) -> bool:
    from PIL import Image, ImageDraw
    top, bottom, accent = _CARD_PALETTES[scene_index % len(_CARD_PALETTES)]
    img = Image.new("RGB", (width, height), top)
    px = ImageDraw.Draw(img)
    for y in range(height):  # vertical gradient
        t = y / (height - 1)
        px.line([(0, y), (width, y)], fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    for x in range(-height, width, 120):  # subtle angled grid lines
        px.line([(x, height), (x + height, 0)], fill=tuple(min(255, c + 10) for c in bottom), width=2)
    d = ImageDraw.Draw(img)
    d.ellipse([width - 360, height - 520, width + 220, height + 60], fill=tuple(min(255, c + 14) for c in bottom))

    margin = 70
    y_badge = 140

    # 1. Exam Tag Pill (e.g. "IBPS SO IT")
    tag = (tag or "").upper().strip()
    tag_w = 0
    if tag:
        f_tag = _card_font(38)
        tag_w = int(d.textlength(tag, font=f_tag))
        d.rounded_rectangle([margin, y_badge, margin + tag_w + 50, y_badge + 72], radius=36, fill=accent)
        d.text((margin + 25, y_badge + 15), tag, font=f_tag, fill=(10, 14, 24))

    # 2. Curiosity Badge Pill (e.g. "⚡ 3-SEC SHORTCUT")
    badge = _CURIOUS_BADGES[scene_index % len(_CURIOUS_BADGES)]
    f_badge = _card_font(34, bold=True)
    badge_x = margin + tag_w + 70 if tag else margin
    badge_w = int(d.textlength(badge, font=f_badge))
    badge_end = min(width - margin, badge_x + badge_w + 50)
    d.rounded_rectangle([badge_x, y_badge, badge_end, y_badge + 72], radius=36, outline=accent, width=3)
    d.text((badge_x + 25, y_badge + 16), badge, font=f_badge, fill=(255, 255, 255))

    # 3. Main Headline (1-2 punchy lines)
    headline = " ".join((headline or "").split())
    y = 260
    if headline:
        size = 80
        while size >= 52:
            f_h = _card_font(size)
            lines = _wrap_px(d, headline, f_h, width - 2 * margin)
            if len(lines) <= 2:
                break
            size -= 6
        for ln in lines[:2]:
            d.text((margin, y), ln, font=f_h, fill=(255, 255, 255))
            y += int(size * 1.15)
        d.rectangle([margin, y + 8, margin + 220, y + 16], fill=accent)
        y += 45

    # 4. Single High-Impact Memory Anchor Card (no text walls — pure takeaway)
    anchor_text = ""
    valid_points = [p.strip() for p in points if p and p.strip()]
    if valid_points:
        anchor_text = valid_points[0]
    elif headline and len(headline.split()) <= 6:
        anchor_text = headline

    if anchor_text:
        anchor_clean = anchor_text.upper()
        f_anchor = _card_font(46, bold=True)
        anchor_lines = _wrap_px(d, anchor_clean, f_anchor, width - 2 * margin - 80)[:2]
        card_h = 44 + len(anchor_lines) * 58
        card_bg = tuple(min(255, c + 24) for c in top)

        # Glowing container for the memory anchor
        d.rounded_rectangle([margin, y, width - margin, y + card_h], radius=24, fill=card_bg, outline=accent, width=3)
        d.rounded_rectangle([margin, y, margin + 14, y + card_h], radius=6, fill=accent)

        ty = y + 22
        for al in anchor_lines:
            d.text((margin + 44, ty), al, font=f_anchor, fill=accent)
            ty += 58

    # The middle zone (Y: 650 to 1400) is now completely clear for the animated karaoke captions!
    img.save(out_path, "JPEG", quality=92)
    return out_path.exists() and out_path.stat().st_size > 5_000



def _render_procedural_backdrop(out_path: Path, scene_index: int, subject_area: str = "default", width: int = 1080, height: int = 1920) -> bool:
    """Procedural fallback when all external visual APIs are rate-limited or unavailable.
    Creates a sleek dark-cinematic abstract vertical backdrop with deep contrast gradients,
    subtle grid geometry, and glowing ambient accents.
    """
    try:
        from PIL import Image, ImageDraw
        # Color palettes based on subject area
        palettes = {
            "economy": ((6, 12, 28), (14, 28, 54), (0, 200, 255)),
            "science": ((10, 8, 30), (28, 16, 68), (180, 80, 255)),
            "geography": ((4, 24, 28), (10, 56, 60), (40, 220, 180)),
            "history": ((24, 14, 8), (56, 32, 16), (255, 170, 50)),
            "default": ((8, 14, 24), (18, 32, 52), (0, 215, 255)),
        }
        top, bottom, accent = palettes.get(subject_area, palettes["default"])
        img = Image.new("RGB", (width, height), top)
        d = ImageDraw.Draw(img)

        # Smooth vertical gradient
        for y in range(height):
            t = y / (height - 1)
            r = int(top[0] + (bottom[0] - top[0]) * t)
            g = int(top[1] + (bottom[1] - top[1]) * t)
            b = int(top[2] + (bottom[2] - top[2]) * t)
            d.line([(0, y), (width, y)], fill=(r, g, b))

        # Ambient glowing orb in upper third
        orb_x, orb_y = width // 2 + (scene_index % 2 * 200 - 100), height // 3
        for radius in range(350, 0, -25):
            alpha = int(22 * (1 - radius / 350))
            col = tuple(min(255, c + alpha) for c in bottom)
            d.ellipse([orb_x - radius, orb_y - radius, orb_x + radius, orb_y + radius], fill=col)

        # Subtle dark tech grid lines
        grid_step = 160
        for x in range(0, width, grid_step):
            d.line([(x, 0), (x, height)], fill=tuple(min(255, c + 6) for c in bottom), width=1)
        for y in range(0, height, grid_step):
            d.line([(0, y), (width, y)], fill=tuple(min(255, c + 6) for c in bottom), width=1)

        img.save(out_path, "JPEG", quality=92)
        print(f"[visuals] generated procedural backdrop for scene {scene_index}")
        return True
    except Exception as exc:
        print(f"[visuals] procedural backdrop failed: {exc}")
        return False


def _apply_dark_scrim(path: Path, width: int = 1080, height: int = 1920) -> bool:
    """Burn a calibrated vertical dark gradient scrim over the image so that
    HUD text and animated karaoke captions always stay legible over any complex
    AI-generated background. Used exclusively for `cinematic_hud` style.

    Scrim recipe:
      - Top 30%  : 55% opacity dark fade (room for badge & hook text)
      - Bottom 30%: 65% opacity dark fade (room for karaoke captions)
      - Middle 40%: transparent (lets the WOW visual breathe)
    """
    try:
        from PIL import Image, ImageDraw
        with Image.open(path) as img:
            img = img.convert("RGBA")
            scrim = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            draw = ImageDraw.Draw(scrim)
            # Top gradient band
            top_band = int(height * 0.30)
            for y in range(top_band):
                alpha = int(140 * (1 - y / top_band))  # 140→0
                draw.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))
            # Bottom gradient band
            bottom_start = int(height * 0.70)
            for y in range(bottom_start, height):
                t = (y - bottom_start) / (height - bottom_start)
                alpha = int(165 * t)  # 0→165
                draw.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))
            composite = Image.alpha_composite(img, scrim).convert("RGB")
            composite.save(path, "JPEG", quality=92)
        return True
    except Exception as exc:
        print(f"[visuals] dark scrim failed (non-fatal): {exc}")
        return False



def _cloudflare_scene_enabled() -> bool:
    """Return True when Cloudflare FLUX.1 Schnell is the active image provider."""
    enabled = os.getenv("CLOUDFLARE_SCENE_IMAGES_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
    return bool(os.getenv("IMAGE_PROVIDER", "cloudflare").strip().lower() == "cloudflare" and enabled and cloudflare_configured())


def _fetch_cloudflare_scene_image(
    prompt: str,
    out_path: Path,
    seed: int,
    width: int = 768,
    height: int = 1365,
) -> bool:
    """Generate a vertical scene image through the active Cloudflare model."""
    if PROVIDER_STATE.get("cloudflare_image") != "available" or not _cloudflare_scene_enabled():
        return False

    clean_prompt = " ".join((prompt or "").split()).strip()
    if not clean_prompt:
        return False
    scene_prompt = clean_prompt
    if "9:16" not in scene_prompt.lower() and "vertical" not in scene_prompt.lower():
        scene_prompt += ", vertical 9:16 composition"

    try:
        image = _generate_cloudflare_image_with_dimensions(scene_prompt, seed, width=width, height=height, steps=4)
        temp = out_path.with_suffix(".cloudflare.jpg")
        image.save(temp, "JPEG", quality=94)
        if _valid_image(temp) and _normalize_image(temp, 1080, 1920):
            temp.replace(out_path)
            model = os.getenv("CLOUDFLARE_IMAGE_MODEL", "").split("/")[-1]
            print(f"[visuals] Cloudflare {model} generated scene -> {out_path.name}")
            return True
    except Exception as exc:
        print(f"[visuals] Cloudflare scene generation failed: {exc}")
        PROVIDER_STATE["cloudflare_image"] = "disabled"
    return False

def _generate_cloudflare_image_with_dimensions(
    prompt: str,
    seed: int,
    width: int | None,
    height: int | None,
    steps: int = 4,
) -> Image.Image:
    """Call the shared Cloudflare adapter using the configured model transport."""
    target_w = int(width or 1024)
    target_h = int(height or 1024)
    return generate_cloudflare_background(prompt, seed, width=target_w, height=target_h, model=os.getenv("CLOUDFLARE_SCENE_MODEL", os.getenv("CLOUDFLARE_IMAGE_MODEL", "@cf/black-forest-labs/flux-1-schnell")))


def fetch_scene_image(
    scene_index: int, image_prompt: str, visual_style: str, settings, subject_area: str = "default",
    card_headline: str = "", card_points: list[str] | None = None, card_tag: str = "",
) -> Path:
    out_path = WORK_DIR / f"scene_{scene_index:02d}.jpg"
    if visual_style == "text_card":
        out_path.unlink(missing_ok=True)
        if not _render_text_card(out_path, scene_index, card_headline, card_points or [], card_tag):
            raise RuntimeError(f"Could not render text card for scene {scene_index}")
        return out_path

    full_prompt = _premium_prompt(image_prompt, visual_style, subject_area)
    if _valid_image(out_path):
        return out_path
    out_path.unlink(missing_ok=True)

    fetched = False

    # 1. PRIMARY AI IMAGE PROVIDER: Cloudflare Workers AI + FLUX.1 Schnell.
    # Gemini image generation is deliberately disabled here. Gemini remains
    # active for text/script generation and its image code is retained for a
    # later opt-in when a supported/affordable image endpoint is available.
    if _cloudflare_scene_enabled():
        scene_seed = int(hashlib.sha256(f"{scene_index}:{image_prompt}".encode("utf-8")).hexdigest()[:8], 16)
        print(f"[visuals] scene {scene_index}: generating via Cloudflare FLUX.1 Schnell...")
        fetched = _fetch_cloudflare_scene_image(
            full_prompt,
            out_path,
            seed=scene_seed,
            width=int(os.getenv("CLOUDFLARE_SCENE_WIDTH", "768")),
            height=int(os.getenv("CLOUDFLARE_SCENE_HEIGHT", "1365")),
        )

    # 2. Gemini image generation is intentionally NOT called in production.
    # Keep _fetch_gemini_image() above for a future explicit opt-in.

    # 3. Stock fallback: Pexels, when configured.
    if not fetched and settings.pexels_api_key:
        scene_query = _extract_scene_pexels_query(image_prompt, subject_area)
        print(f"[visuals] scene {scene_index}: querying pexels with scene-specific query: {scene_query!r}")
        if _fetch_pexels(scene_query, out_path, settings.pexels_api_key, scene_index=scene_index):
            fetched = True

        if not fetched:
            fallback_query = _DARK_PEXELS_FALLBACK.get(subject_area, "dark abstract technology background")
            print(f"[visuals] scene {scene_index}: retrying pexels with fallback: {fallback_query!r}")
            if _fetch_pexels(fallback_query, out_path, settings.pexels_api_key, scene_index=scene_index):
                fetched = True

    if not fetched:
        print(f"[visuals] scene {scene_index}: all external APIs exhausted -> falling back to procedural backdrop")
        if _render_procedural_backdrop(out_path, scene_index, subject_area):
            fetched = True
        else:
            raise RuntimeError(f"Could not fetch or generate a visual for scene {scene_index}: {image_prompt!r}")

    # For cinematic_hud, burn a calibrated dark gradient scrim so that the
    # progress bar, hook sweep, badge, and karaoke captions always pop with
    # perfect contrast over any complex AI-generated background.
    if visual_style == "cinematic_hud":
        _apply_dark_scrim(out_path)

    return out_path
