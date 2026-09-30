"""Hosted AI thumbnail background adapters.

Primary provider: Cloudflare Workers AI + FLUX.2 [klein] 4B.
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
CLOUDFLARE_SCENE_MODEL = os.getenv(
    "CLOUDFLARE_SCENE_MODEL",
    CLOUDFLARE_MODEL,
).strip()
CLOUDFLARE_THUMBNAIL_MODEL = os.getenv(
    "CLOUDFLARE_THUMBNAIL_MODEL",
    "@cf/black-forest-labs/flux-2-klein-4b",
).strip()
CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
_INITIAL_CLOUDFLARE_ACCOUNT_ID = CLOUDFLARE_ACCOUNT_ID
_INITIAL_CLOUDFLARE_API_TOKEN = CLOUDFLARE_API_TOKEN
THUMBNAIL_AI_URL = os.getenv("THUMBNAIL_AI_URL", "").strip()
THUMBNAIL_AI_TOKEN = os.getenv("THUMBNAIL_AI_TOKEN", "").strip()
THUMBNAIL_AI_TIMEOUT = max(15, int(os.getenv("THUMBNAIL_AI_TIMEOUT", "180")))
CLOUDFLARE_IMAGE_STEPS = min(8, max(1, int(os.getenv("CLOUDFLARE_IMAGE_STEPS", "4"))))


def _effective_cloudflare_credentials() -> tuple[str, str]:
    # Environment variables are the normal production source (GitHub Actions
    # secrets). If a test/runtime override changes either module global after
    # import, honor that override so provider disabling and endpoint tests are
    # deterministic even when CI itself has Cloudflare secrets configured.
    if CLOUDFLARE_ACCOUNT_ID != _INITIAL_CLOUDFLARE_ACCOUNT_ID or CLOUDFLARE_API_TOKEN != _INITIAL_CLOUDFLARE_API_TOKEN:
        return CLOUDFLARE_ACCOUNT_ID.strip(), CLOUDFLARE_API_TOKEN.strip()
    return (os.getenv("CLOUDFLARE_ACCOUNT_ID", CLOUDFLARE_ACCOUNT_ID).strip(),
            os.getenv("CLOUDFLARE_API_TOKEN", CLOUDFLARE_API_TOKEN).strip())


def cloudflare_configured() -> bool:
    account, token = _effective_cloudflare_credentials()
    return bool(account and token)


def cloudflare_endpoint(account_id: str | None = None, model: str | None = None) -> str:
    account_default, _ = _effective_cloudflare_credentials()
    model_default = CLOUDFLARE_MODEL
    account = (account_id if account_id is not None else account_default).strip()
    model_name = (model if model is not None else model_default).strip()
    if not account:
        raise ValueError("CLOUDFLARE_ACCOUNT_ID is required")
    if not model_name:
        raise ValueError("CLOUDFLARE_IMAGE_MODEL is required")
    return f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model_name}"


def build_cloudflare_payload(prompt: str, seed: int, steps: int | None = None, width: int = 1280, height: int = 720) -> dict[str, Any]:
    """Safe JSON payload for FLUX.1 Schnell REST.

    Some Workers AI accounts reject optional seed/size fields even though older
    examples documented them. The production adapter therefore starts with the
    smallest portable schema: prompt only.
    """
    del seed, steps, width, height
    clean_prompt = " ".join(str(prompt or "").split()).strip()
    if not clean_prompt:
        raise ValueError("prompt must not be empty")
    return {"prompt": clean_prompt[:2048]}


def build_flux2_multipart_fields(prompt: str, seed: int, width: int = 1152, height: int = 768) -> dict[str, tuple[None, str]]:
    """Multipart form fields required by Cloudflare FLUX.2 klein models."""
    clean_prompt = " ".join(str(prompt or "").split()).strip()
    if not clean_prompt:
        raise ValueError("prompt must not be empty")
    return {
        "prompt": (None, clean_prompt[:2048]),
        "width": (None, str(int(width))),
        "height": (None, str(int(height))),
        "seed": (None, str(int(seed))),
    }

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


def generate_cloudflare_background(
    prompt: str,
    seed: int,
    width: int = 1280,
    height: int = 720,
    model: str | None = None,
) -> Image.Image:
    """Generate with the requested Cloudflare model, handling model-specific REST schemas."""
    model_name = (model or os.getenv("CLOUDFLARE_IMAGE_MODEL", CLOUDFLARE_MODEL)).strip()
    endpoint = cloudflare_endpoint(model=model_name)
    _, token = _effective_cloudflare_credentials()
    timeout = max(15, int(os.getenv("CLOUDFLARE_IMAGE_TIMEOUT", str(THUMBNAIL_AI_TIMEOUT))))
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json,image/*"}

    if "flux-2-klein" in model_name.lower():
        # FLUX.2 klein currently uses multipart form fields and fixed 4-step inference.
        fields = build_flux2_multipart_fields(prompt, seed, width=max(256, int(width)), height=max(256, int(height)))
        response = requests.post(endpoint, headers=headers, files=fields, timeout=timeout)
        if response.status_code >= 400:
            detail = response.text.replace(token, "***")[:1200]
            raise RuntimeError(f"Cloudflare Workers AI HTTP {response.status_code}: {detail}")
        return parse_cloudflare_response(response)

    # FLUX.1 Schnell: start with the minimal JSON schema. If an account still
    # rejects the request, retry once with prompt-only to avoid seed/schema drift.
    payload = build_cloudflare_payload(prompt, seed, steps=4, width=width, height=height)
    response = requests.post(
        endpoint,
        headers={**headers, "Content-Type": "application/json"},
        json=payload,
        timeout=timeout,
    )
    if response.status_code >= 400:
        detail = response.text.replace(token, "***")[:1200]
        # The first payload is already prompt-only, so this branch only reports the provider error.
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
    """Use Cloudflare FLUX.2 [klein] 4B as the active image generator.

    The generic endpoint remains available only for compatibility; it is not
    selected unless explicitly enabled via THUMBNAIL_ALLOW_GENERIC=true.
    """
    if cloudflare_configured():
        primary = os.getenv("CLOUDFLARE_THUMBNAIL_MODEL", CLOUDFLARE_THUMBNAIL_MODEL).strip()
        try:
            return generate_cloudflare_background(prompt, seed, width=1152, height=768, model=primary), "cloudflare"
        except Exception as exc:
            print(f"[thumbnail-ai] Cloudflare thumbnail model {primary} failed; trying FLUX.1 fallback: {exc}")
            fallback_model = os.getenv("CLOUDFLARE_SCENE_MODEL", "@cf/black-forest-labs/flux-1-schnell").strip()
            if fallback_model and fallback_model != primary:
                try:
                    return generate_cloudflare_background(prompt, seed, width=1280, height=720, model=fallback_model), "cloudflare-flux1-fallback"
                except Exception as fallback_exc:
                    print(f"[thumbnail-ai] FLUX.1 fallback failed; falling back: {fallback_exc}")

    if THUMBNAIL_AI_URL and os.getenv("THUMBNAIL_ALLOW_GENERIC", "false").strip().lower() in {"1", "true", "yes", "on"}:
        try:
            return generate_generic_background(prompt, seed), "generic"
        except Exception as exc:
            print(f"[thumbnail-ai] generic generation failed; falling back: {exc}")

    return None, "local"
