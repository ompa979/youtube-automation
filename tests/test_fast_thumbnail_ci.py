"""Fast CI smoke tests for thumbnail-only changes.

These checks intentionally cover only the thumbnail contract and Cloudflare
failover boundary. The complete regression suite remains available as the
manual `full` CI mode.
"""
from pathlib import Path
from unittest.mock import patch
import importlib
import json
import os
import tempfile

from PIL import Image


def _reload_ai():
    import pipeline.thumbnail_ai as ai
    return importlib.reload(ai)


def test_cloudflare_pool_reads_four_accounts(monkeypatch):
    values = {
        "CLOUDFLARE_ACCOUNT_ID": "acct1",
        "CLOUDFLARE_API_TOKEN": "tok1",
        "CLOUDFLARE_ACCOUNT_ID_2": "acct2",
        "CLOUDFLARE_API_TOKEN_2": "tok2",
        "CLOUDFLARE_ACCOUNT_ID_3": "acct3",
        "CLOUDFLARE_API_TOKEN_3": "tok3",
        "CLOUDFLARE_ACCOUNT_ID_4": "acct4",
        "CLOUDFLARE_API_TOKEN_4": "tok4",
        "CLOUDFLARE_MAX_ACCOUNTS": "4",
    }
    for k, v in values.items():
        monkeypatch.setenv(k, v)
    ai = _reload_ai()
    assert [slot for slot, _, _ in ai.cloudflare_credential_pool()] == ["1", "2", "3", "4"]


def test_cloudflare_failover_moves_after_quota_error(monkeypatch):
    for k, v in {
        "CLOUDFLARE_ACCOUNT_ID": "acct1",
        "CLOUDFLARE_API_TOKEN": "tok1",
        "CLOUDFLARE_ACCOUNT_ID_2": "acct2",
        "CLOUDFLARE_API_TOKEN_2": "tok2",
        "CLOUDFLARE_MAX_ACCOUNTS": "2",
        "CLOUDFLARE_THUMBNAIL_MODEL": "@cf/black-forest-labs/flux-2-klein-4b",
        "CLOUDFLARE_SCENE_MODEL": "",
    }.items():
        monkeypatch.setenv(k, v)
    ai = _reload_ai()
    calls = []

    def fake_generate(prompt, seed, width, height, model, account_id, api_token):
        calls.append(account_id)
        if account_id == "acct1":
            raise RuntimeError("HTTP 429 daily free allocation exhausted")
        return Image.new("RGB", (32, 32), (20, 60, 120))

    with patch.object(ai, "generate_cloudflare_background", side_effect=fake_generate):
        im, provider = ai.generate_background("hero", 7)

    assert im is not None and im.size == (32, 32)
    assert calls[:2] == ["acct1", "acct2"]
    assert "acct2" in provider


def test_shorts_native_dimensions_and_legacy_helper_contract():
    import pipeline.engagement_v2 as ev2
    assert (ev2.THUMBNAIL_W, ev2.THUMBNAIL_H) == (2160, 3840)
    legacy = ev2._v11_procedural_hero("TCP 3-way handshake", 0)
    native = ev2._v12_procedural_hero("TCP 3-way handshake", 0)
    assert legacy.size == (1280, 720)
    assert native.size == (2160, 3840)


def test_thumbnail_manifest_patch_id_and_canvas(tmp_path):
    import pipeline.engagement_v2 as ev2
    bg = ev2._v12_procedural_hero("TCP 3-way handshake", 0)
    out = tmp_path / "thumbnail.jpg"
    ev2._v12_render(bg, out, "3-WAY HANDSHAKE", "SYN → SYN-ACK → ACK", "IBPS SO IT", 0)
    with Image.open(out) as im:
        assert im.size == (2160, 3840)


def test_scene_provider_uses_primary_credentials_only(monkeypatch):
    import pipeline.visuals as visuals
    monkeypatch.setenv("IMAGE_PROVIDER", "cloudflare")
    monkeypatch.setenv("CLOUDFLARE_SCENE_IMAGES_ENABLED", "true")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct1")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID_2", "acct2")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN_2", "tok2")
    assert visuals._cloudflare_scene_enabled() is False
