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
