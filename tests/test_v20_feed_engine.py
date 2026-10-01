from datetime import datetime, timedelta, timezone

from pipeline.v20_topic_engine import V20_SEED, generate_v20_spec
from pipeline.v20_upload import create_v20_upload_body
from pipeline.v20_telemetry import OBSERVATION_HOURS


def test_v20_seed_is_exactly_40_and_balanced():
    assert len(V20_SEED) == 40
    counts = {}
    for fmt, *_ in V20_SEED:
        counts[fmt] = counts.get(fmt, 0) + 1
    assert counts == {"BRAIN_TRAP": 10, "OPTICAL_ILLUSION": 10, "SATISFYING": 10, "MICRO_LOOP": 10}


def test_v20_spec_has_frame_zero_hook_and_no_search_intent():
    spec = generate_v20_spec(1)
    assert spec["distribution_goal"] == "SHORTS_FEED"
    assert spec["search_intent"] is False
    assert spec["loop_frame_match"] is True
    assert spec["hook_text"]


def test_v20_upload_is_minimal_entertainment_metadata():
    body = create_v20_upload_body(generate_v20_spec(1))
    assert body["snippet"]["categoryId"] == "24"
    assert body["snippet"]["tags"] == ["shorts"]
    assert body["snippet"]["description"].startswith("#shorts")
    assert generate_v20_spec(1)["tracking_tag"] in body["snippet"]["description"]
    assert "V20-" not in body["snippet"]["title"]


def test_v20_evaluation_gate_is_72_hours():
    assert OBSERVATION_HOURS == 72


def test_v20_flux_prompt_is_subtype_specific():
    a = generate_v20_spec(1)
    b = generate_v20_spec(31)
    assert a["visual_prompt"] != b["visual_prompt"]
    assert "9:16" in a["visual_prompt"]
    assert "frame zero" in a["visual_prompt"]



def test_v20_source_contracts_are_not_slideshow_contracts():
    for i in range(1, 41):
        spec = generate_v20_spec(i)
        if spec["format"] == "SATISFYING":
            assert spec["source_contract"] == "REAL_MOTION_VIDEO"
            assert spec["stock_video_query"]
        else:
            assert spec["source_contract"] == "SINGLE_CANVAS"
