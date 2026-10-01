import importlib
import os
from pathlib import Path
import sys

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_v18_copy_is_topic_specific():
    mod = importlib.import_module('pipeline.engagement_v2')
    pack = mod._v18_viral_copy('Why compound growth looks boring before it suddenly accelerates', '', '')
    assert pack['headline'] == 'BORING → EXPLOSIVE'
    assert 'MONEY' in pack['strap']
    assert len(pack['calls']) == 3


def test_v18_render_has_reference_layout(tmp_path):
    mod = importlib.import_module('pipeline.engagement_v2')
    bg = mod._v12_procedural_hero('compound growth money investing', 0)
    pack = mod._v18_viral_copy('Why compound growth looks boring before it suddenly accelerates', '', '')
    out = tmp_path / 'v18.jpg'
    meta = mod._v18_render(bg, out, pack, 0)
    assert out.exists()
    with Image.open(out) as im:
        assert im.size == (2160, 3840)
        assert im.mode == 'RGB'
    assert meta['engine'] == 'v18_indian_viral_explainer'
    assert meta['layout'] == 'yellow_top_red_strap_hero_black_callouts_red_payoff'


def test_v18_create_thumbnail_routes_only_viral_mode(tmp_path, monkeypatch):
    mod = importlib.import_module('pipeline.engagement_v2')
    bg = mod._v12_procedural_hero('compound growth money investing', 0)
    bg_path = tmp_path / 'bg.jpg'
    bg.save(bg_path)
    monkeypatch.setenv('CONTENT_MODE', 'viral')
    monkeypatch.setattr(mod, '_request_ai_background', lambda prompt, seed: bg.copy())
    out = tmp_path / 'thumbnail.jpg'
    result = mod.create_custom_thumbnail(Path('missing.mp4'), out, 0.5, '', 'VIRAL', background_path=bg_path,
                                         topic='Why compound growth looks boring before it suddenly accelerates', variants=5)
    assert result == out
    with Image.open(out) as im:
        assert im.size == (2160, 3840)
    manifest = out.parent / 'thumbnail_variants' / 'manifest.json'
    assert manifest.exists()
    text = manifest.read_text(encoding='utf-8')
    assert 'v18_indian_viral_explainer' in text
    assert 'yellow_top_red_strap_hero_black_callouts_red_payoff' in text
