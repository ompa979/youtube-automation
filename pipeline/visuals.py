"""Premium visual acquisition for educational Shorts.

AI imagery is preferred because it can depict the actual mechanism being taught.
Pexels is a fallback for photographic subjects. Every prompt is upgraded with a
cinematic editorial art direction while preserving the scene's educational idea.
"""
from __future__ import annotations

import hashlib
import random
import time
import urllib.parse
from pathlib import Path

import requests
from PIL import Image

from .config import WORK_DIR

POLLINATIONS = "https://image.pollinations.ai/prompt/{prompt}"

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


def _valid_image(path: Path) -> bool:
    try:
        with Image.open(path) as img:
            width, height = img.size
            return width >= 720 and height >= 1280 and path.stat().st_size >= 20_000
    except Exception:
        return False


def _fetch_pollinations(prompt: str, out_path: Path, width: int = 1080, height: int = 1920, attempts: int = 3) -> bool:
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
            r = requests.get(url, params=params, timeout=150)
            r.raise_for_status()
            if len(r.content) < 20_000:
                raise RuntimeError(f"response too small ({len(r.content)} bytes) — likely an error page, not an image")
            out_path.write_bytes(r.content)
            if not _valid_image(out_path):
                raise RuntimeError("downloaded file failed image validation (bad dimensions/corrupt)")
            return True
        except Exception as exc:
            last_error = exc
            out_path.unlink(missing_ok=True)
            print(f"[visuals] pollinations attempt {attempt}/{attempts} failed: {exc}")
            if attempt < attempts:
                time.sleep(3 * attempt)  # 3s, 6s backoff — pollinations is often just momentarily overloaded

    print(f"[visuals] pollinations exhausted all attempts: {last_error}")
    return False


def _fetch_pexels(query: str, out_path: Path, api_key: str) -> bool:
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
            if _valid_image(out_path):
                return True
            out_path.unlink(missing_ok=True)
        print(f"[visuals] pexels: none of {len(candidates)} candidates passed image validation for query {query!r}")
        return False
    except Exception as exc:
        out_path.unlink(missing_ok=True)
        print(f"[visuals] pexels failed for query {query!r}: {exc}")
        return False


def _premium_prompt(image_prompt: str, visual_style: str) -> str:
    base = " ".join((image_prompt or "").split())
    # Very long prompts can make free image APIs time out or silently reject
    # the request. Cap it defensively — the schema already asks the LLM for
    # 20-45 words, so this only trims runaway outliers.
    if len(base) > 600:
        base = base[:600].rsplit(" ", 1)[0]
    suffix = STYLE_SUFFIX.get(visual_style, STYLE_SUFFIX["educational_ai"])
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
        + text_note
    )


def fetch_scene_image(scene_index: int, image_prompt: str, visual_style: str, settings) -> Path:
    prompt = _premium_prompt(image_prompt, visual_style)
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
