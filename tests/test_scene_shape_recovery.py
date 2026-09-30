from types import SimpleNamespace
import json
import sys, types
try:
    import google.generativeai  # type: ignore
except Exception:
    google_mod = types.ModuleType("google")
    genai_mod = types.ModuleType("google.generativeai")
    setattr(google_mod, "generativeai", genai_mod)
    sys.modules.setdefault("google", google_mod)
    sys.modules.setdefault("google.generativeai", genai_mod)
import pipeline.script_gen as sg

ROLES = ["hook", "context", "mechanism", "example", "exam_takeaway", "difference_card"]

def _scene(role, i):
    return {
        "action_type": role,
        "action_payload": f"show {role}",
        "narration": f"Useful teaching line for {role} with enough detail.",
        "tts_text": f"Useful teaching line for {role} with enough detail.",
        "image_prompt": "premium editorial visual, no text",
        "on_screen_text": role.replace('_', ' '),
        "card_points": [role],
        "motion_type": "push_in",
        "camera_motion": "push_in",
        "sfx_cue": "whoosh",
    }

class FakeRouter:
    def __init__(self, payload): self.payload = payload; self.calls=[]
    def generate(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        return json.dumps(self.payload)


def test_scene_shape_recovery_from_five_scenes():
    source = {"scenes": [_scene(r, i) for i, r in enumerate(ROLES[:5])]}
    repaired = {"scenes": [_scene(r, i) for i, r in enumerate(ROLES)]}
    router = FakeRouter(repaired)
    out = sg._safe_to_script(source, router, "TCP vs UDP")
    assert len(out.scenes) == 6
    assert [s.action_type for s in out.scenes] == ROLES
    assert router.calls


class SequenceRouter:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []
    def generate(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        payload = self.payloads.pop(0)
        return json.dumps(payload)


def test_scene_shape_recovery_retries_clean_generation_when_repair_returns_empty():
    source = {"title": "TCP handshake", "scenes": []}
    empty_repair = {"script": {"title": "TCP handshake", "scenes": []}}
    recovered = {"scenes": [_scene(r, i) for i, r in enumerate(ROLES)]}
    router = SequenceRouter([empty_repair, recovered])
    out = sg._safe_to_script(source, router, "TCP 3-way handshake")
    assert len(out.scenes) == 6
    assert len(router.calls) == 2
    assert router.calls[0][1]["call_type"] == sg.CallType.JSON_REPAIR
    assert router.calls[1][1]["call_type"] == sg.CallType.SCRIPT_GEN


def test_scene_shape_extractor_unwraps_script_wrapper():
    wrapped = {"result": {"script": {"scenes": [_scene(r, i) for i, r in enumerate(ROLES)]}}}
    scenes = sg._extract_scene_list(wrapped)
    assert len(scenes) == 6
