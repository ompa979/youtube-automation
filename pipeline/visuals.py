"""Premium visual acquisition for educational Shorts.

AI imagery is preferred because it can depict the actual mechanism being taught.
Pexels is a fallback for photographic subjects. Every prompt is upgraded with a
cinematic editorial art direction while preserving the scene's educational idea.
"""
from __future__ import annotations

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

POLLINATIONS = "https://image.pollinations.ai/prompt/{prompt}"

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
        "layered depth, dramatic studio lighting, realistic textures, visually striking but accurate, "
        "vertical 9:16, no text, no logos, no watermark"
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


def _fetch_pollinations(prompt: str, out_path: Path, width: int = 1080, height: int = 1920, attempts: int = 2) -> bool:
    encoded = urllib.parse.quote(prompt, safe="")
    url = POLLINATIONS.format(prompt=encoded)
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        params = {
            "width": width,
            "height": height,
            "nologo": "true",
            "model": "flux",
            "seed": random.randint(1, 2_000_000_000),
        }
        try:
            with _POLLINATIONS_SEMAPHORE:
                r = requests.get(url, params=params, timeout=45)
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
            if attempt < attempts:
                is_429 = "429" in str(exc) or "Too Many Requests" in str(exc)
                time.sleep(8 if is_429 else 2)  # 429s need real cooldown, not a token retry

    print(f"[visuals] pollinations exhausted all attempts: {last_error}")
    return False


def _fetch_pexels(query: str, out_path: Path, api_key: str, width: int = 1080, height: int = 1920) -> bool:
    try:
        r = requests.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": api_key},
            params={
                "query": query,
                "orientation": "portrait",
                "per_page": 5,
                "size": "large",
            },
            timeout=45,
        )
        r.raise_for_status()
        photos = r.json().get("photos", [])
        if not photos:
            print(f"[visuals] pexels returned 0 results for query {query!r}")
            return False
        # Pick the highest-resolution candidate instead of blindly taking photo 1.
        candidates = sorted(
            photos,
            key=lambda p: int(p.get("width", 0)) * int(p.get("height", 0)),
            reverse=True,
        )
        for photo in candidates:
            src = photo.get("src", {}).get("large2x") or photo.get("src", {}).get("original")
            if not src:
                continue
            img = requests.get(src, timeout=90)
            img.raise_for_status()
            out_path.write_bytes(img.content)
            if _valid_image(out_path) and _normalize_image(out_path, width, height):
                return True
            out_path.unlink(missing_ok=True)
        print(f"[visuals] pexels: none of {len(candidates)} candidates passed image validation for query {query!r}")
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


def fetch_scene_image(
    scene_index: int, image_prompt: str, visual_style: str, settings, subject_area: str = "default"
) -> Path:
    prompt = _premium_prompt(image_prompt, visual_style, subject_area)
    out_path = WORK_DIR / f"scene_{scene_index:02d}.jpg"

    if _valid_image(out_path):
        return out_path
    out_path.unlink(missing_ok=True)

    if _fetch_pollinations(prompt, out_path):
        return out_path

    if settings.pexels_api_key:
        # Pexels works best with a concise photographic search phrase.
        short = " ".join((image_prompt or "cinematic educational concept").split()[:10])
        if _fetch_pexels(short, out_path, settings.pexels_api_key):
            return out_path
        # The specific phrase can return zero results; retry once with a
        # broad, near-guaranteed-to-match fallback query rather than failing
        # the whole scene (and wasting every scene generated before it).
        broad_query = "education abstract concept illustration"
        print(f"[visuals] scene {scene_index}: specific pexels query failed, retrying with broad fallback")
        if _fetch_pexels(broad_query, out_path, settings.pexels_api_key):
            return out_path

    raise RuntimeError(
        f"Could not fetch a valid premium visual for scene {scene_index}: {image_prompt!r}"
    )
