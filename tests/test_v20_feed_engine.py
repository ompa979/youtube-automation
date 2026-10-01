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


def test_brain_trap_target_is_off_center_and_renderer_uses_target_strategy():
    spec = generate_v20_spec(1)
    assert spec["format"] == "BRAIN_TRAP"
    assert spec["reveal_strategy"] == "PUNCH_ZOOM_TARGET"
    assert spec["target_point"]["x"] > 0.60
    assert spec["target_point"]["y"] < 0.50
    assert "FOUND IT" not in spec["hook_text"]


def test_brain_trap_prompt_forbids_center_anomaly_and_multiscene():
    spec = generate_v20_spec(1)
    prompt = spec["visual_prompt"].lower()
    assert "no eye" in prompt or "no anomaly" in prompt
    assert "no alternate scenes" in prompt
    assert "no slideshow" in prompt


def test_v20_renderer_keeps_single_canvas_motion_and_lower_hud():
    from pathlib import Path
    renderer = Path(__file__).resolve().parents[1] / "pipeline" / "v20_renderer.py"
    source = renderer.read_text()
    assert "zoompan=" in source
    assert "y=1510" in source
    assert "PUNCH_ZOOM_TARGET" in source
    # No arbitrary reveal circle is allowed in the Brain Trap renderer.
    assert "drawellipse" not in source
    assert "drawcircle" not in source


def test_v20_quality_rejects_static_canvas(tmp_path):
    import subprocess
    from PIL import Image
    from pipeline.quality import verify_v20_quality

    image = tmp_path / "static.jpg"
    Image.new("RGB", (1080, 1920), (35, 20, 45)).save(image, quality=95)
    video = tmp_path / "static.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(image),
        "-f", "lavfi", "-i", "sine=frequency=440:duration=8",
        "-t", "8", "-r", "30", "-s", "1080x1920",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(video)
    ], check=True)
    result = verify_v20_quality(video, "BRAIN_TRAP")
    assert not result.ok
    assert any("effectively static" in issue for issue in result.issues)
