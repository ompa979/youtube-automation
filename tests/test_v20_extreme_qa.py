import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

from pipeline.quality import verify_v20_quality, verify_v20_spec
from pipeline.v20_topic_engine import generate_v20_spec


def _make_video(tmp_path: Path, *, color=(35, 20, 45), duration=8.0, motion=False, freeze=False):
    image = tmp_path / "source.jpg"
    if motion:
        # Non-uniform deterministic canvas so camera movement is measurable.
        im = Image.new("RGB", (1080, 1920), color)
        draw = ImageDraw.Draw(im)
        for y in range(0, 1920, 48):
            for x in range(0, 1080, 48):
                if ((x // 48) + (y // 48)) % 2 == 0:
                    draw.rectangle((x, y, x + 24, y + 24), fill=(180, 60, 210))
        im.save(image, quality=95)
    else:
        Image.new("RGB", (1080, 1920), color).save(image, quality=95)
    out = tmp_path / ("motion.mp4" if motion else "static.mp4")
    if motion:
        # Real deterministic motion for the positive-path test.
        vf = "scale=1080:1920,zoompan=z='1+0.0012*on':d=240:s=1080x1920:fps=30"
    else:
        vf = "scale=1080:1920"
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(image),
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
        "-vf", vf, "-t", str(duration), "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", str(out),
    ]
    subprocess.run(cmd, check=True)
    return out


def test_extreme_spec_rejects_missing_brain_target():
    spec = generate_v20_spec(1)
    spec["target_point"] = None
    assert any("target_point" in x for x in verify_v20_spec(spec))


def test_extreme_spec_rejects_center_target():
    spec = generate_v20_spec(1)
    spec["target_point"] = {"x": 0.50, "y": 0.50}
    assert any("too close to visual center" in x for x in verify_v20_spec(spec))


def test_extreme_spec_rejects_multi_scene_contract():
    spec = generate_v20_spec(1)
    spec["source_contract"] = "MULTI_SCENE"
    assert any("multi-scene" in x for x in verify_v20_spec(spec))


def test_extreme_qa_rejects_static_video(tmp_path):
    video = _make_video(tmp_path, motion=False)
    result = verify_v20_quality(video, "BRAIN_TRAP")
    assert not result.ok
    assert any("motion" in x for x in result.issues)


def test_extreme_qa_accepts_real_continuous_motion(tmp_path):
    video = _make_video(tmp_path, motion=True)
    result = verify_v20_quality(video, "BRAIN_TRAP")
    assert result.ok, result.issues
    assert result.active_motion_ratio >= 0.95
    assert result.max_freeze_frames <= 6


def test_extreme_qa_rejects_blank_canvas(tmp_path):
    video = _make_video(tmp_path, color=(0, 0, 0), motion=False)
    result = verify_v20_quality(video, "BRAIN_TRAP")
    assert not result.ok
    assert any("near-black" in x for x in result.issues)


def test_extreme_qa_requires_exact_v20_duration(tmp_path):
    video = _make_video(tmp_path, duration=6.0, motion=True)
    result = verify_v20_quality(video, "BRAIN_TRAP")
    assert not result.ok
    assert any("duration" in x for x in result.issues)


def test_renderer_has_no_center_target_fallback_for_punch_zoom():
    source = (Path(__file__).resolve().parents[1] / "pipeline" / "v20_renderer.py").read_text()
    assert 'target = spec.get("target_point")' in source
    assert 'requires an explicit target_point' in source
    assert "drawcircle" not in source
    assert "drawellipse" not in source


def test_extreme_qa_rejects_real_hard_cut(tmp_path):
    a = tmp_path / "a.jpg"
    b = tmp_path / "b.jpg"
    Image.new("RGB", (1080, 1920), (0, 0, 0)).save(a)
    Image.new("RGB", (1080, 1920), (255, 255, 255)).save(b)
    out = tmp_path / "cut.mp4"
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-loop", "1", "-t", "4", "-i", str(a),
        "-loop", "1", "-t", "4", "-i", str(b),
        "-f", "lavfi", "-i", "sine=frequency=440:duration=8",
        "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0,scale=1080:1920,fps=30[v]",
        "-map", "[v]", "-map", "2:a", "-t", "8", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", str(out),
    ]
    subprocess.run(cmd, check=True)
    result = verify_v20_quality(out, "BRAIN_TRAP")
    assert not result.ok
    assert result.hard_cuts >= 1


def test_all_canvas_formats_require_zoompan_and_satisfying_is_real_video():
    source = (Path(__file__).resolve().parents[1] / "pipeline" / "v20_renderer.py").read_text()
    assert source.count("zoompan=") >= 2
    assert "SATISFYING requires exactly one real motion-video source" in source
    assert "stream_loop" in source
    # The satisfying branch must use stream_loop, not a still-image loop.
    satisfying = source[source.index("def _render_satisfying_video"):source.index("def _render_micro_loop")]
    assert "-stream_loop" in satisfying
    assert '"-loop", "1", "-i"' not in satisfying
