"""Image acquisition: Pollinations (no key) primary, Pexels stock fallback."""
from __future__ import annotations

import hashlib
import random
import urllib.parse
from pathlib import Path

import requests

from .config import WORK_DIR

POLLINATIONS = "https://image.pollinations.ai/prompt/{prompt}"
STYLE_SUFFIX = {
    "text_gradient_ai": ", minimal, high contrast, vertical composition, dramatic lighting, no text",
    "mixed_stock_ai": ", photographic, realistic, vertical 9:16 composition, natural lighting, no text",
    "ai_cinematic": ", cinematic, film still, moody atmospheric lighting, 35mm, vertical 9:16, no text",
    "educational_ai": ", clean educational infographic style, clear subject separation, simple diagram-friendly composition, arrows or visual relationships when relevant, vertical 9:16, no text, no logos",
}

def _fetch_pollinations(prompt: str, out_path: Path, width: int = 1080, height: int = 1920) -> bool:
    encoded = urllib.parse.quote(prompt, safe="")
    url = POLLINATIONS.format(prompt=encoded)
    params = {
        "width": width,
        "height": height,
        "nologo": "true",
        "model": "flux",
        "seed": random.randint(1, 2_000_000_000),
    }
    try:
        r = requests.get(url, params=params, timeout=120)
        r.raise_for_status()
        if len(r.content) < 5_000:
            return False
        out_path.write_bytes(r.content)
        return True
    except Exception:
        return False

def _fetch_pexels(query: str, out_path: Path, api_key: str) -> bool:
    try:
        r = requests.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": api_key},
            params={"query": query, "orientation": "portrait", "per_page": 1, "size": "large"},
            timeout=45,
        )
        r.raise_for_status()
        photos = r.json().get("photos", [])
        if not photos:
            return False
        src = photos[0]["src"]["large2x"]
        img = requests.get(src, timeout=90)
        img.raise_for_status()
        out_path.write_bytes(img.content)
        return True
    except Exception:
        return False

def fetch_scene_image(scene_index: int, image_prompt: str, visual_style: str, settings) -> Path:
    suffix = STYLE_SUFFIX.get(visual_style, STYLE_SUFFIX["text_gradient_ai"])
    full_prompt = f"{image_prompt}{suffix}"

    out_path = WORK_DIR / f"scene_{scene_index:02d}.jpg"
    if out_path.exists() and out_path.stat().st_size > 5_000:
        return out_path

    if _fetch_pollinations(full_prompt, out_path):
        return out_path

    if settings.pexels_api_key:
        short = " ".join(image_prompt.split()[:6])
        if _fetch_pexels(short, out_path, settings.pexels_api_key):
            return out_path

    raise RuntimeError(f"Could not fetch image for scene {scene_index}: {image_prompt!r}")
