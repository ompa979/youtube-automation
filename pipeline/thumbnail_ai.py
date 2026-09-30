"""Hosted AI thumbnail background adapters.

Primary provider: Cloudflare Workers AI + FLUX.1 [schnell].
Fallback provider: legacy generic THUMBNAIL_AI_URL endpoint.

The final thumbnail typography/layout is still owned by Pillow in
``engagement_v2.py``; this module only supplies a clean hero background.
"""
from __future__ import annotations

import base64
import io
import json
import os
from pathlib import Path
from typing import Any

import requests
from PIL import Image

CLOUDFLARE_MODEL = os.getenv(
    "CLOUDFLARE_IMAGE_MODEL",
    "@cf/black-forest-labs/flux-1-schnell",
).strip()
CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
THUMBNAIL_AI_URL = os.getenv("THUMBNAIL_AI_URL", "").strip()
THUMBNAIL_AI_TOKEN = os.getenv("THUMBNAIL_AI_TOKEN", "").strip()
THUMBNAIL_AI_TIMEOUT = max(15, int(os.getenv("THUMBNAIL_AI_TIMEOUT", "180")))
CLOUDFLARE_IMAGE_STEPS = min(8, max(1, int(os.getenv("CLOUDFLARE_IMAGE_STEPS", "4"))))


def cloudflare_configured() -> bool:
    account = os.getenv("CLOUDFLARE_ACCOUNT_ID", CLOUDFLARE_ACCOUNT_ID).strip()
    token = os.getenv("CLOUDFLARE_API_TOKEN", CLOUDFLARE_API_TOKEN).strip()
    return bool(account and token)


def cloudflare_endpoint(account_id: str | None = None, model: str | None = None) -> str:
    account_default = os.getenv("CLOUDFLARE_ACCOUNT_ID", CLOUDFLARE_ACCOUNT_ID)
    model_default = os.getenv("CLOUDFLARE_IMAGE_MODEL", CLOUDFLARE_MODEL)
    account = (account_id or account_default).strip()
    model_name = (model or model_default).strip()
    if not account:
        raise ValueError("CLOUDFLARE_ACCOUNT_ID is required")
    if not model_name:
        raise ValueError("CLOUDFLARE_IMAGE_MODEL is required")
    return f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model_name}"


def build_cloudflare_payload(prompt: str, seed: int, steps: int | None = None) -> dict[str, Any]:
    """Return the REST payload documented for FLUX.1 Schnell."""
    clean_prompt = " ".join(str(prompt or "").split()).strip()
    if not clean_prompt:
        raise ValueError("prompt must not be empty")
    step_count = CLOUDFLARE_IMAGE_STEPS if steps is None else int(steps)
    if step_count < 1 or step_count > 8:
        raise ValueError("steps must be between 1 and 8")
    return {"prompt": clean_prompt[:2048], "seed": int(seed), "steps": step_count, "width": 1280, "height": 720}


def _decode_base64_image(value: str) -> Image.Image:
    raw = value
    if raw.startswith("data:image/") and "," in raw:
        raw = raw.split(",", 1)[1]
    binary = base64.b64decode(raw, validate=False)
    return Image.open(io.BytesIO(binary)).convert("RGB")


def parse_cloudflare_response(response: requests.Response) -> Image.Image:
    """Parse REST output. Cloudflare documents result.image as base64."""
    content_type = response.headers.get("content-type", "").lower()
    if content_type.startswith("image/"):
        return Image.open(io.BytesIO(response.content)).convert("RGB")

    payload: dict[str, Any] = response.json()
    result = payload.get("result") if isinstance(payload.get("result"), dict) else payload
    image_b64 = result.get("image") if isinstance(result, dict) else None
    if isinstance(image_b64, str) and image_b64:
        return _decode_base64_image(image_b64)

    # Be defensive for a generic gateway wrapper.
    for key in ("image_base64", "data"):
        value = result.get(key) if isinstance(result, dict) else None
        if isinstance(value, str) and value:
            return _decode_base64_image(value)

    image_url = result.get("image_url") if isinstance(result, dict) else None
    if isinstance(image_url, str) and image_url:
        image_response = requests.get(image_url, timeout=THUMBNAIL_AI_TIMEOUT)
        image_response.raise_for_status()
        return Image.open(io.BytesIO(image_response.content)).convert("RGB")

    raise RuntimeError("Cloudflare image response did not contain an image")


def generate_cloudflare_background(prompt: str, seed: int) -> Image.Image:
    endpoint = cloudflare_endpoint()
    payload = build_cloudflare_payload(prompt, seed)
    token = os.getenv("CLOUDFLARE_API_TOKEN", CLOUDFLARE_API_TOKEN).strip()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json,image/*",
    }
    timeout = max(15, int(os.getenv("CLOUDFLARE_IMAGE_TIMEOUT", str(THUMBNAIL_AI_TIMEOUT))))
    response = requests.post(endpoint, headers=headers, json=payload, timeout=timeout)
    if response.status_code >= 400:
        # Do not include the token in logs/errors.
        detail = response.text.replace(token, "***")[:1200]
        raise RuntimeError(f"Cloudflare Workers AI HTTP {response.status_code}: {detail}")
    return parse_cloudflare_response(response)


def generate_generic_background(prompt: str, seed: int) -> Image.Image:
    if not THUMBNAIL_AI_URL:
        raise RuntimeError("No generic thumbnail AI endpoint configured")
    headers = {"Accept": "image/png,application/json"}
    if THUMBNAIL_AI_TOKEN:
        headers["Authorization"] = f"Bearer {THUMBNAIL_AI_TOKEN}"
    payload = {"prompt": prompt, "width": 1152, "height": 648, "seed": int(seed)}
    response = requests.post(THUMBNAIL_AI_URL, json=payload, headers=headers, timeout=THUMBNAIL_AI_TIMEOUT)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "").lower()
    if content_type.startswith("image/"):
        return Image.open(io.BytesIO(response.content)).convert("RGB")
    data = response.json()
    if data.get("image_base64"):
        return _decode_base64_image(data["image_base64"])
    if data.get("image_url"):
        image_response = requests.get(data["image_url"], timeout=THUMBNAIL_AI_TIMEOUT)
        image_response.raise_for_status()
        return Image.open(io.BytesIO(image_response.content)).convert("RGB")
    raise RuntimeError("Generic thumbnail AI endpoint returned no image data")


def generate_background(prompt: str, seed: int) -> tuple[Image.Image | None, str]:
    """Use Cloudflare FLUX.1 Schnell as the active image generator.

    The generic endpoint remains available only for compatibility; it is not
    selected unless explicitly enabled via THUMBNAIL_ALLOW_GENERIC=true.
    """
    if cloudflare_configured():
        try:
            return generate_cloudflare_background(prompt, seed), "cloudflare"
        except Exception as exc:
            print(f"[thumbnail-ai] Cloudflare generation failed; falling back: {exc}")

    if THUMBNAIL_AI_URL and os.getenv("THUMBNAIL_ALLOW_GENERIC", "false").strip().lower() in {"1", "true", "yes", "on"}:
        try:
            return generate_generic_background(prompt, seed), "generic"
        except Exception as exc:
            print(f"[thumbnail-ai] generic generation failed; falling back: {exc}")

    return None, "local"
