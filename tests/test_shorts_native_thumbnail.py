from pathlib import Path
import importlib
import json
import os
import sys

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_thumbnail_dimensions_are_shorts_native():
    mod = importlib.import_module("pipeline.engagement_v2")
    assert mod.THUMBNAIL_W == 2160
    assert mod.THUMBNAIL_H == 3840
    assert round(mod.THUMBNAIL_W / mod.THUMBNAIL_H, 3) == 0.562


def test_cloudflare_thumbnail_pool_has_four_slots(monkeypatch):
    for k, v in {
        "CLOUDFLARE_ACCOUNT_ID": "a1",
        "CLOUDFLARE_API_TOKEN": "t1",
        "CLOUDFLARE_ACCOUNT_ID_2": "a2",
        "CLOUDFLARE_API_TOKEN_2": "t2",
        "CLOUDFLARE_ACCOUNT_ID_3": "a3",
        "CLOUDFLARE_API_TOKEN_3": "t3",
        "CLOUDFLARE_ACCOUNT_ID_4": "a4",
        "CLOUDFLARE_API_TOKEN_4": "t4",
    }.items():
        monkeypatch.setenv(k, v)
    mod = importlib.reload(importlib.import_module("pipeline.thumbnail_ai"))
    slots = mod.cloudflare_credential_pool()
    assert [s[0] for s in slots] == ["1", "2", "3", "4"]


def test_v12_manifest_safe_area_metadata(tmp_path, monkeypatch):
    mod = importlib.import_module("pipeline.engagement_v2")
    bg = mod._v12_procedural_hero("TCP 3-way handshake", 0)
    out = tmp_path / "thumb.jpg"
    meta = mod._v12_render(bg, out, "3-WAY HANDSHAKE", "SYN → SYN-ACK → ACK", "IBPS SO IT", 0)
    with Image.open(out) as im:
        assert im.size == (2160, 3840)
        assert im.mode == "RGB"
    assert meta["canvas"] == [2160, 3840]
    assert meta["safe_center_45"] == [570, 3270]
