from __future__ import annotations

import base64
import io
import tempfile
import unittest
from pathlib import Path

from PIL import Image
import requests

from types import SimpleNamespace
import pipeline.thumbnail_ai as ai
import pipeline.engagement_v2 as ev2


def _script(question: str, topic: str = "RBI Grade B - Test Topic") -> Script:
    scenes = [
        SimpleNamespace(index=0, narration="Stop.", tts_text="Stop.", image_prompt="hero", on_screen_text="STOP", card_points=[], action_type="explanation", action_payload=""),
        SimpleNamespace(index=1, narration=question, tts_text=question, image_prompt="challenge", on_screen_text="A OR B?", card_points=["TEST RULE"], action_type="explanation", action_payload=""),
        SimpleNamespace(index=2, narration="Three two one.", tts_text="Three two one.", image_prompt="count", on_screen_text="THINK FAST", card_points=[], action_type="explanation", action_payload=""),
        SimpleNamespace(index=3, narration="Answer.", tts_text="Answer.", image_prompt="reveal", on_screen_text="REVEAL", card_points=["ANSWER"], action_type="explanation", action_payload=""),
        SimpleNamespace(index=4, narration="Rule.", tts_text="Rule.", image_prompt="mechanism", on_screen_text="THE TRICK", card_points=["RULE"], action_type="explanation", action_payload=""),
        SimpleNamespace(index=5, narration=question, tts_text=question, image_prompt="trap", on_screen_text="DID YOU GET IT?", card_points=[], action_type="explanation", action_payload=""),
    ]
    return SimpleNamespace(
        title=topic, hook=question, description="", tags=[], scenes=scenes,
        pinned_comment="", thumbnail_text="",
    )


def _fake_cf_response() -> requests.Response:
    img = Image.new("RGB", (64, 64), (17, 90, 140))
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    payload = {"success": True, "result": {"image": base64.b64encode(bio.getvalue()).decode("ascii")}}
    r = requests.Response()
    r.status_code = 200
    r.headers["content-type"] = "application/json"
    import json
    r._content = json.dumps(payload).encode("utf-8")
    return r


# Build exactly 100 independent unittest cases.  The suite intentionally covers
# parsing, title/CTA rules, archetype routing, Cloudflare payload/response logic,
# deterministic compositor output, and fallback behavior.
class TestThumbnailEngine100(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Never allow an inherited local machine secret to make this test suite
        # call a real hosted provider. Live provider verification belongs in CI.
        cls._orig = (
            ai.CLOUDFLARE_ACCOUNT_ID,
            ai.CLOUDFLARE_API_TOKEN,
            ai.THUMBNAIL_AI_URL,
        )
        ai.CLOUDFLARE_ACCOUNT_ID = ""
        ai.CLOUDFLARE_API_TOKEN = ""
        ai.THUMBNAIL_AI_URL = ""

    @classmethod
    def tearDownClass(cls):
        ai.CLOUDFLARE_ACCOUNT_ID, ai.CLOUDFLARE_API_TOKEN, ai.THUMBNAIL_AI_URL = cls._orig


# 01-30: question extraction and challenge text behavior
QUESTION_CASES = [
    "Which one uses cash reserves?",
    "Which protocol can lose the packet?",
    "Can you spot the correct answer?",
    "What is the IFSC length?",
    "Where does this deposit belong?",
    "Why does M3 include term deposits?",
    "How many characters are here?",
    "What happens after SYN?",
    "Which normal form removes this dependency?",
    "Which layer routes the packet?",
    "Can you solve this in 5 seconds?",
    "Which one is broader?",
    "Who controls the reserve?",
    "Where is the bug?",
    "Why is this answer wrong?",
    "How many digits does it contain?",
    "Which one is correct?",
    "Can you find the output?",
    "What comes next?",
    "Which statement is false?",
    "Where does FD go?",
    "Why does TCP wait?",
    "How do you calculate this?",
    "Which shortcut works here?",
    "Can you beat the trap?",
    "What is the answer?",
    "Which option survives?",
    "Why is SLR different?",
    "How many steps?",
    "Which choice would you pick?",
]
for idx, q in enumerate(QUESTION_CASES, 1):
    def make_case(q=q):
        def case(self):
            result = ev2._question_from_challenge(_script(q))
            self.assertTrue(result)
            self.assertIn("?", result)
        return case
    setattr(TestThumbnailEngine100, f"test_{idx:03d}_question_{idx}", make_case())

# 31-50: archetype routing
ARCHETYPE_CASES = [
    ("TCP vs UDP difference", "Which one can lose the packet?", "compare"),
    ("CRR vs SLR", "Which one uses cash?", "compare"),
    ("Exam trap", "Which answer is wrong?", "trap"),
    ("common mistake", "Where is the pitfall?", "trap"),
    ("SQL query output", "Find the output?", "output"),
    ("machine input output", "What comes next?", "output"),
    ("how many digits", "How many digits?", "number"),
    ("percentage", "What percent?", "number"),
    ("formula calculation", "How do you calculate this?", "formula"),
    ("simplification", "Can you calculate this?", "formula"),
    ("true or false", "True or false?", "true_false"),
    ("correct statement", "Which statement is correct?", "true_false"),
    ("why does this happen", "Why does it happen?", "mystery"),
    ("secret reason", "What is the hidden reason?", "mystery"),
    ("boss fight", "Can you beat this?", "boss_fight"),
    ("challenge level", "Can you crack it?", "boss_fight"),
    ("simple question", "Which one?", "question"),
    ("general concept", "Can you get it right?", "question"),
    ("one answer", "What is the answer?", "question"),
    ("topic mystery", "Why?", "mystery"),
]
for offset, (topic, question, expected) in enumerate(ARCHETYPE_CASES, 31):
    def make_case(topic=topic, question=question, expected=expected):
        def case(self):
            self.assertEqual(ev2._thumbnail_archetype(topic, question, 0), expected)
        return case
    setattr(TestThumbnailEngine100, f"test_{offset:03d}_archetype", make_case())

# 51-65: thumbnail text rules
TEXT_CASES = [
    "Which one uses cash reserves?",
    "Does FD count?",
    "Can you solve this?",
    "Which protocol can lose the packet?",
    "What is the IFSC length?",
    "Where does this deposit belong?",
    "Why does M3 include term deposits?",
    "How many characters are here?",
    "Which normal form removes this dependency?",
    "Which layer routes the packet?",
    "Can you find the output?",
    "Which statement is false?",
    "Where is the bug?",
    "How do you calculate this?",
    "Which shortcut works here?",
]
for offset, q in enumerate(TEXT_CASES, 51):
    def make_case(q=q):
        def case(self):
            value = ev2.build_thumbnail_text(_script(q))
            self.assertEqual(value, value.upper())
            self.assertLessEqual(len(value), 53)
            self.assertNotIn("\n", value)
        return case
    setattr(TestThumbnailEngine100, f"test_{offset:03d}_thumbnail_text", make_case())

# 66-75: title/CTA packaging
for offset, q in enumerate([
    "Which one uses cash reserves?", "Which protocol can lose the packet?",
    "What is the IFSC length?", "Does FD count?", "Where is the bug?",
    "How do you calculate this?", "Which statement is false?", "Can you find the output?",
    "Why does M3 include term deposits?", "Which layer routes the packet?",
], 66):
    def make_case(q=q):
        def case(self):
            script = _script(q, "RBI Grade B - Money Supply")
            title = ev2.build_click_title("RBI Grade B - Money Supply", script.title, script)
            cta = ev2.build_comment_cta(script)
            self.assertLessEqual(len(title), 85)
            self.assertIn("?", cta)
            self.assertNotIn("exam date", cta.lower())
        return case
    setattr(TestThumbnailEngine100, f"test_{offset:03d}_packaging", make_case())

# 76-80: contract normalization
for offset in range(76, 81):
    def make_case(offset=offset):
        def case(self):
            script = _script(f"Which answer wins in case {offset}?")
            ev2.enforce_v2_contract(script)
            roles = [s.action_type for s in script.scenes]
            self.assertEqual(tuple(roles), ev2.V2_ACTION_SEQUENCE)
            self.assertTrue(script.thumbnail_text)
        return case
    setattr(TestThumbnailEngine100, f"test_{offset:03d}_contract", make_case())

# 81-85: Cloudflare endpoint/payload
for offset, seed in enumerate([1, 17, 123, 999, 987654], 81):
    def make_case(seed=seed):
        def case(self):
            ai.CLOUDFLARE_ACCOUNT_ID = "abc123"
            url = ai.cloudflare_endpoint()
            payload = ai.build_cloudflare_payload("cinematic banking scene", seed, 4)
            self.assertIn("abc123", url)
            self.assertIn("flux-1-schnell", url)
            self.assertEqual(payload["seed"], seed)
            self.assertEqual(payload["steps"], 4)
        return case
    setattr(TestThumbnailEngine100, f"test_{offset:03d}_cloudflare_payload", make_case())

# 86-90: Cloudflare payload validation and response parsing
VALIDATION_CASES = ["", "   ", "A valid prompt", "A" * 2048, "A" * 2049]
for offset, prompt in enumerate(VALIDATION_CASES, 86):
    def make_case(prompt=prompt):
        def case(self):
            if not prompt.strip():
                with self.assertRaises(ValueError):
                    ai.build_cloudflare_payload(prompt, 1)
            else:
                payload = ai.build_cloudflare_payload(prompt, 1)
                self.assertLessEqual(len(payload["prompt"]), 2048)
        return case
    setattr(TestThumbnailEngine100, f"test_{offset:03d}_payload_validation", make_case())

# 91-95: Cloudflare response parsing and provider routing
def _fake_data_uri_response() -> requests.Response:
    img = Image.new("RGB", (32, 32), (170, 40, 50))
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    value = "data:image/png;base64," + base64.b64encode(bio.getvalue()).decode("ascii")
    import json
    r = requests.Response()
    r.status_code = 200
    r.headers["content-type"] = "application/json"
    r._content = json.dumps({"success": True, "result": {"image": value}}).encode("utf-8")
    return r

def _fake_bad_response() -> requests.Response:
    r = requests.Response()
    r.status_code = 200
    r.headers["content-type"] = "application/json"
    r._content = b'{"success":true,"result":{}}'
    return r


def test_case_091(self):
    im = ai.parse_cloudflare_response(_fake_cf_response())
    self.assertEqual(im.size, (64, 64))

def test_case_092(self):
    im = ai.parse_cloudflare_response(_fake_data_uri_response())
    self.assertEqual(im.size, (32, 32))

def test_case_093(self):
    original = ai.generate_cloudflare_background
    cfg = (ai.CLOUDFLARE_ACCOUNT_ID, ai.CLOUDFLARE_API_TOKEN)
    try:
        ai.CLOUDFLARE_ACCOUNT_ID = "acct"
        ai.CLOUDFLARE_API_TOKEN = "token"
        ai.generate_cloudflare_background = lambda prompt, seed: Image.new("RGB", (8, 8), (1, 2, 3))
        im, provider = ai.generate_background("x", 1)
        self.assertEqual(provider, "cloudflare")
        self.assertEqual(im.size, (8, 8))
    finally:
        ai.CLOUDFLARE_ACCOUNT_ID, ai.CLOUDFLARE_API_TOKEN = cfg
        ai.generate_cloudflare_background = original

def test_case_094(self):
    original = (ai.CLOUDFLARE_ACCOUNT_ID, ai.CLOUDFLARE_API_TOKEN, ai.THUMBNAIL_AI_URL)
    try:
        ai.CLOUDFLARE_ACCOUNT_ID = ""
        ai.CLOUDFLARE_API_TOKEN = ""
        ai.THUMBNAIL_AI_URL = ""
        im, provider = ai.generate_background("x", 1)
        self.assertIsNone(im)
        self.assertEqual(provider, "local")
    finally:
        ai.CLOUDFLARE_ACCOUNT_ID, ai.CLOUDFLARE_API_TOKEN, ai.THUMBNAIL_AI_URL = original

def test_case_095(self):
    with self.assertRaises(RuntimeError):
        ai.parse_cloudflare_response(_fake_bad_response())

for offset, fn in enumerate([test_case_091, test_case_092, test_case_093, test_case_094, test_case_095], 91):
    setattr(TestThumbnailEngine100, f"test_{offset:03d}_cloudflare_response", fn)

# 96-100: real local compositor smoke cases (AI is disabled in this suite).
for offset, q in enumerate([
    "CRR OR SLR?", "M1 OR M3?", "TCP OR UDP?", "TRUE OR TRAP?", "FIND THE OUTPUT?"
], 96):
    def make_case(q=q):
        def case(self):
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                bg = root / "bg.png"
                out = root / "thumbnail.jpg"
                Image.new("RGB", (1024, 1024), (20, 70, 110)).save(bg)
                script = _script(q)
                ev2.create_custom_thumbnail(
                    root / "unused.mp4", out, 1.0, q, "RBI GRADE B",
                    background_path=bg, topic="RBI Grade B - Test", variants=1
                )
                with Image.open(out) as im:
                    self.assertEqual(im.size, (1280, 720))
                    self.assertEqual(im.format, "JPEG")
                manifest = root / "thumbnail_variants" / "manifest.json"
                self.assertTrue(manifest.exists())
        return case
    setattr(TestThumbnailEngine100, f"test_{offset:03d}_compositor", make_case())


if __name__ == "__main__":
    unittest.main(verbosity=2)
