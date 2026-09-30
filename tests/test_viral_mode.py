import json
import os
from pathlib import Path
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def test_viral_plan_contains_broad_content_pillars():
    data = json.loads((ROOT / "viral_content_plan.json").read_text(encoding="utf-8"))
    niches = data["niches"]
    assert len(niches) >= 8
    assert all(v.get("content_mode") == "viral" for v in niches.values())
    topics = [t for cfg in niches.values() for t in cfg.get("topics", [])]
    assert len(topics) >= 70


def test_viral_topic_selector_uses_viral_gate(monkeypatch):
    monkeypatch.setenv("CONTENT_MODE", "viral")
    monkeypatch.setenv("VIRAL_CONTENT_ONLY", "true")
    monkeypatch.setenv("MIN_VIRAL_SCORE", "62")
    monkeypatch.setenv("TOPIC_USE_TRENDS", "false")
    monkeypatch.setenv("TOPIC_USE_AUTOCOMPLETE", "false")

    from pipeline.topic_engine import choose_best_topic
    data = json.loads((ROOT / "viral_content_plan.json").read_text(encoding="utf-8"))
    plan = data["niches"]
    enabled = list(plan)[:4]
    niche, cfg, lang, topic, score, board = choose_best_topic(
        plan, enabled, {"recent_topics": [], "completed_topics": [], "topic_cursors": {}}
    )
    assert niche in enabled
    assert cfg["content_mode"] == "viral"
    assert lang == "en"
    assert score.viral_fit >= 62
    assert board


def test_viral_script_prompt_is_story_not_exam_quiz():
    from pipeline.script_gen import _build_prompt
    cfg = {
        "content_mode": "viral",
        "system_prompt": "Explain one everyday mechanism with care.",
        "visual_style": "ai_cinematic",
        "voice": {"en": "en-IN"},
    }
    prompt = _build_prompt("Why unfinished tasks stay in your mind longer", cfg, "en")
    assert "pattern_interrupt" in prompt
    assert "transformation" in prompt
    assert "Do not" in prompt
    assert "A/B quiz" in prompt
    assert "Target 60-85 spoken words" in prompt


def test_viral_contract_removes_exam_labels():
    from pipeline.script_gen import Script, Scene
    from pipeline.engagement_v2 import enforce_v2_contract, build_click_title, build_comment_cta
    scenes = [
        Scene(i, f"line {i}", f"line {i}", "hero object", "", [], "explanation", "", "", "", "")
        for i in range(6)
    ]
    script = Script("Test", "hook", "desc", [], scenes, content_mode="viral")
    enforce_v2_contract(script)
    assert [s.action_type for s in script.scenes] == [
        "pattern_interrupt", "tension", "mechanism", "transformation", "payoff", "loop"
    ]
    assert "EXAM" not in build_click_title("Why unfinished tasks stay in your mind longer", "Test", script).upper()
    assert build_comment_cta(script)


def test_scene_failover_moves_from_account_1_to_account_2(monkeypatch, tmp_path):
    import pipeline.visuals as visuals

    monkeypatch.setenv("IMAGE_PROVIDER", "cloudflare")
    monkeypatch.setenv("CLOUDFLARE_SCENE_IMAGES_ENABLED", "true")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct1")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "tok1")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID_2", "acct2")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN_2", "tok2")
    monkeypatch.setenv("CLOUDFLARE_MAX_ACCOUNTS", "2")
    visuals.reset_provider_state()

    calls = []

    def fake_generate(prompt, seed, width, height, model, account_id, api_token):
        calls.append(account_id)
        if account_id == "acct1":
            raise RuntimeError("HTTP 429 daily free allocation exhausted")
        return Image.effect_noise((768, 1365), 70).convert("RGB")

    out = tmp_path / "scene.jpg"
    with patch.object(visuals, "generate_cloudflare_background", side_effect=fake_generate):
        assert visuals._fetch_cloudflare_scene_image("glowing brain", out, 11)
    assert calls == ["acct1", "acct2"]
    assert out.exists()
    with Image.open(out) as img:
        assert img.size == (1080, 1920)


def test_workflow_maps_exam_to_creds_1_and_viral_to_creds_2():
    src = (ROOT / ".github" / "workflows" / "generate.yml").read_text(encoding="utf-8")
    assert "content_mode:" in src
    assert "viral" in src
    assert 'YOUTUBE_CREDENTIAL_PREFIX: "YT_CREDS"' in src
    assert "YOUTUBE_CREDENTIAL_INDICES" in src
    assert "inputs.content_mode == 'viral' && '2' || '1'" in src
    assert "VIRAL_YT_CREDS_1" not in src


def test_viral_settings_use_yt_creds_2(monkeypatch):
    from pipeline.generate import _load_settings
    import base64, json
    payload = {"token":"t","refresh_token":"r","client_id":"id","client_secret":"secret"}
    blob = base64.b64encode(json.dumps(payload).encode()).decode()
    monkeypatch.setenv("CONTENT_MODE", "viral")
    monkeypatch.setenv("YOUTUBE_CREDENTIAL_PREFIX", "YT_CREDS")
    monkeypatch.delenv("YOUTUBE_CREDENTIAL_INDICES", raising=False)
    monkeypatch.delenv("YT_CREDS_1", raising=False)
    monkeypatch.setenv("YT_CREDS_2", blob)
    settings = _load_settings()
    assert [x.index for x in settings.youtube_projects] == [2]


def test_exam_settings_use_yt_creds_1(monkeypatch):
    from pipeline.generate import _load_settings
    import base64, json
    payload = {"token":"t","refresh_token":"r","client_id":"id","client_secret":"secret"}
    blob = base64.b64encode(json.dumps(payload).encode()).decode()
    monkeypatch.setenv("CONTENT_MODE", "exam")
    monkeypatch.setenv("YOUTUBE_CREDENTIAL_PREFIX", "YT_CREDS")
    monkeypatch.delenv("YOUTUBE_CREDENTIAL_INDICES", raising=False)
    monkeypatch.setenv("YT_CREDS_1", blob)
    monkeypatch.delenv("YT_CREDS_2", raising=False)
    settings = _load_settings()
    assert [x.index for x in settings.youtube_projects] == [1]


def test_viral_script_json_parser_supports_viral_action_types():
    from pipeline.script_gen import _v6_to_script

    roles = ["pattern_interrupt", "tension", "mechanism", "transformation", "payoff", "loop"]
    data = {
        "title": "Why compound growth suddenly accelerates",
        "hook": "At first, compound growth barely looks like growth.",
        "description": "A simple visual explanation of compounding. #money #finance #shorts",
        "pinned_comment": "When did compounding finally click for you?",
        "tags": ["money", "finance", "compoundgrowth"],
        "scenes": [
            {
                "action_type": role,
                "narration": "A simple test line with a concrete visual change.",
                "tts_text": "A simple test line with a concrete visual change.",
                "image_prompt": "A cinematic vertical visual of the exact concept changing visibly, no text.",
                "on_screen_text": "A CLEAR CUE",
                "card_points": ["ONE MEMORY ANCHOR"],
                "action_payload": "show the visual change",
            }
            for role in roles
        ],
    }
    script = _v6_to_script(data)
    assert [s.action_type for s in script.scenes] == roles
    assert script.scenes[0].motion_type == "slam_impact"
    assert script.scenes[1].camera_motion == "push_in"
    assert script.scenes[3].motion_type == "transformation"
    assert script.scenes[5].sfx_cue == "tick"
