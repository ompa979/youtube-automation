
import json
import sys
import types
try:
    import google.generativeai  # type: ignore
except Exception:
    google_mod = types.ModuleType("google")
    genai_mod = types.ModuleType("google.generativeai")
    setattr(google_mod, "generativeai", genai_mod)
    sys.modules.setdefault("google", google_mod)
    sys.modules.setdefault("google.generativeai", genai_mod)

from pathlib import Path

from pipeline.tts import normalize_for_speech
from pipeline.captions import build_word_ass
from pipeline.script_gen import _safe_to_script, _apply_topic_visual_contract


def _scene(i, role):
    return {
        "action_type": role,
        "action_payload": "teaching payload",
        "narration": "Useful networking line with enough detail.",
        "tts_text": "Useful networking line with enough detail.",
        "image_prompt": "premium networking visual, no text",
        "on_screen_text": role.replace("_", " "),
        "card_points": ["teaching anchor"],
        "motion_type": "push_in",
        "camera_motion": "push_in",
        "sfx_cue": "whoosh",
    }


def test_tcp_tts_terms_are_phonetic():
    spoken = normalize_for_speech("TCP sends SYN, then SYN-ACK, then ACK over UDP.")
    assert "Sin" in spoken
    assert "Sin Ack" in spoken
    assert "Ack" in spoken
    assert "S Y N" not in spoken


def test_tcp_contract_injects_exam_arithmetic_and_question():
    data = {
        "title": "TCP 3-Way Handshake Explained",
        "hook": "",
        "description": "",
        "tags": [],
        "scenes": [_scene(i, role) for i, role in enumerate(
            ["hook", "context", "mechanism", "example", "exam_takeaway", "difference_card"]
        )],
    }
    class Router:
        def generate(self, prompt, **kwargs):
            return json.dumps(data)

    # Parser accepts the legacy six-scene shape; the topic contract upgrades TCP.
    from pipeline.script_gen import _to_script
    script = _to_script(data)
    _apply_topic_visual_contract(script, "TCP 3-way handshake")
    assert "Seq=x" in script.scenes[2].action_payload
    assert "Ack=x+1" in script.scenes[2].action_payload
    assert script.scenes[2].motion_type == "tcp_packet_flow"
    assert script.scenes[5].action_type == "exam_question"
    assert "what state does the server enter" in script.scenes[5].narration.lower()
    assert "SYN-RECEIVED" not in script.scenes[5].narration


def test_word_caption_is_one_word_at_a_time(tmp_path: Path):
    out = tmp_path / "captions.ass"
    timings = [
        {"word": "SYN", "start": 0.0, "end": 0.2},
        {"word": "moves", "start": 0.2, "end": 0.4},
        {"word": "first", "start": 0.4, "end": 0.6},
    ]
    assert build_word_ass(timings, 0.6, out)
    text = out.read_text()
    assert "}SYN\n" in text
    assert "}moves\n" in text
    assert "}first\n" in text
