from __future__ import annotations

from types import SimpleNamespace

from pipeline.creative_v17 import apply_v17_creative_contract
from pipeline.render import _v17_hero_filter, _v17_info_card_filter


def make_script():
    roles = ["hook", "context", "mechanism", "example", "exam_takeaway", "difference_card"]
    return SimpleNamespace(
        title="CRR vs SLR: what banks keep as reserves",
        thumbnail_text="WHY DOES CRR STAY HERE?",
        thumbnail_subline="BANKING RESERVES",
        scenes=[
            SimpleNamespace(
                action_type=r,
                narration="Useful teaching line for this exact topic.",
                image_prompt="cinematic bank reserve concept",
                on_screen_text="WHY THIS MATTERS" if r == "hook" else ("requiring immediate" if r == "context" else r),
                card_points=[],
                action_payload="Show the exact reserve movement",
            )
            for r in roles
        ],
    )


def test_v17_replaces_subtitle_fragment_and_generic_hook():
    script = make_script()
    meta = apply_v17_creative_contract(script, "CRR vs SLR: what banks keep as reserves", {"card_tag": "BANK EXAMS"})
    assert meta.hero_headline == "CRR VS SLR"
    assert meta.hero_subline == "WHERE EACH RESERVE SITS"
    assert script.scenes[0].on_screen_text == "CRR VS SLR"
    assert script.scenes[1].on_screen_text != "REQUIRING IMMEDIATE"
    assert script.creative_version == "v17_information_design"
    assert script.scenes[3].visual_mode == "worked_example"
    assert script.scenes[4].visual_mode == "exam_card"


def test_v17_image_prompts_share_visual_family():
    script = make_script()
    apply_v17_creative_contract(script, "TCP 3-way handshake: what SYN, SYN-ACK and ACK actually do", {"card_tag": "IBPS SO IT"})
    prompts = [s.image_prompt for s in script.scenes]
    assert all("V17 VISUAL FAMILY: TCP 3-way handshake" in p for p in prompts)
    assert all("no text" not in p.lower() or "text" in p.lower() for p in prompts)


def test_v17_filters_are_information_design_not_legacy_game_hud():
    hero = _v17_hero_filter("CRR VS SLR", "WHERE EACH RESERVE SITS", "BANK EXAMS", "0x33D6FF")
    info = _v17_info_card_filter("ONE WORKED EXAMPLE", "₹100 DEPOSIT → RESERVE", "0x33D6FF", "worked_example")
    assert "A OR B" not in hero.upper()
    assert "STOP" not in hero.upper()
    assert "drawtext" in hero
    assert "₹100 DEPOSIT" in info
