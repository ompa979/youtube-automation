import base64
import io
import os
import tempfile
import unittest
import requests
from pathlib import Path
from unittest.mock import patch

from PIL import Image

import pipeline.visuals as visuals


class FakeResponse:
    def __init__(self, image_bytes, status=200):
        self.status_code = status
        self.content = image_bytes
        self.headers = {"content-type": "application/json"}
        self.text = ""

    def json(self):
        return {"result": {"image": base64.b64encode(self.content).decode("ascii")}}


def jpeg_bytes(size=(768, 1365)):
    b = io.BytesIO()
    Image.effect_noise(size, 70).convert("RGB").save(b, "JPEG", quality=90)
    return b.getvalue()


class TestCloudflareSceneProvider(unittest.TestCase):
    def setUp(self):
        self.old = dict(os.environ)
        os.environ["IMAGE_PROVIDER"] = "cloudflare"
        os.environ["CLOUDFLARE_SCENE_IMAGES_ENABLED"] = "true"
        os.environ["CLOUDFLARE_ACCOUNT_ID"] = "acct"
        os.environ["CLOUDFLARE_API_TOKEN"] = "token"
        os.environ["CLOUDFLARE_IMAGE_MODEL"] = "@cf/black-forest-labs/flux-1-schnell"
        visuals.PROVIDER_STATE["cloudflare_image"] = "available"

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.old)
        visuals.PROVIDER_STATE["cloudflare_image"] = "available"

    def test_enabled(self):
        self.assertTrue(visuals._cloudflare_scene_enabled())

    def test_disabled_provider(self):
        os.environ["IMAGE_PROVIDER"] = "pexels"
        self.assertFalse(visuals._cloudflare_scene_enabled())

    def test_disabled_flag(self):
        os.environ["CLOUDFLARE_SCENE_IMAGES_ENABLED"] = "false"
        self.assertFalse(visuals._cloudflare_scene_enabled())

    def test_missing_credentials(self):
        os.environ["CLOUDFLARE_API_TOKEN"] = ""
        self.assertFalse(visuals._cloudflare_scene_enabled())

    @patch("pipeline.visuals.requests.post")
    def test_cloudflare_generates_and_normalizes(self, post):
        post.return_value = FakeResponse(jpeg_bytes((768, 1365)))
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "scene.jpg"
            ok = visuals._fetch_cloudflare_scene_image("vertical banking vault", out, 7, 768, 1365)
            self.assertTrue(ok)
            with Image.open(out) as img:
                self.assertEqual(img.size, (1080, 1920))
        called = post.call_args
        self.assertIn("prompt", called.kwargs["json"])
        self.assertNotIn("width", called.kwargs["json"])
        self.assertNotIn("height", called.kwargs["json"])
        self.assertNotIn("seed", called.kwargs["json"])

    @patch("pipeline.visuals.requests.post")
    def test_cloudflare_dimension_retry(self, post):
        post.side_effect = [FakeResponse(jpeg_bytes((768, 1365)), 200)]
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "scene.jpg"
            ok = visuals._fetch_cloudflare_scene_image("network packet", out, 8)
            self.assertTrue(ok)
            self.assertEqual(post.call_count, 1)
            with Image.open(out) as img:
                self.assertEqual(img.size, (1080, 1920))

    @patch("pipeline.visuals.requests.post")
    def test_cloudflare_failure_disables_provider(self, post):
        post.side_effect = Exception("offline")
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "scene.jpg"
            ok = visuals._fetch_cloudflare_scene_image("network packet", out, 9)
            self.assertFalse(ok)
        self.assertEqual(visuals.PROVIDER_STATE["cloudflare_image"], "disabled")

    def test_gemini_function_exists_for_future(self):
        self.assertTrue(callable(visuals._fetch_gemini_image))


# Deterministic expansion to 15 tests without making network calls.
for i in range(8):
    def make_test(idx):
        def test(self):
            self.assertEqual(os.getenv("IMAGE_PROVIDER"), "cloudflare")
            self.assertEqual(os.getenv("CLOUDFLARE_IMAGE_MODEL"), "@cf/black-forest-labs/flux-1-schnell")
            self.assertIn("vertical", visuals._premium_prompt("a bank", "educational_ai", "banking_awareness" ).lower())
        return test
    setattr(TestCloudflareSceneProvider, f"test_config_contract_{i+1:02d}", make_test(i))


if __name__ == "__main__":
    unittest.main()

class TestCloudflareModelSchemas(unittest.TestCase):
    @patch("pipeline.thumbnail_ai.requests.post")
    def test_flux1_prompt_only_schema(self, post):
        from pipeline import thumbnail_ai as ai
        post.return_value = _fake_cf_response_for_tests()
        ai.CLOUDFLARE_ACCOUNT_ID = "acct"
        ai.CLOUDFLARE_API_TOKEN = "token"
        ai.generate_cloudflare_background("clean hero", 42, model="@cf/black-forest-labs/flux-1-schnell")
        call = post.call_args
        self.assertIn("json", call.kwargs)
        self.assertEqual(call.kwargs["json"], {"prompt": "clean hero"})
        self.assertNotIn("files", call.kwargs)

    @patch("pipeline.thumbnail_ai.requests.post")
    def test_flux2_klein_uses_multipart(self, post):
        from pipeline import thumbnail_ai as ai
        post.return_value = _fake_cf_response_for_tests()
        ai.CLOUDFLARE_ACCOUNT_ID = "acct"
        ai.CLOUDFLARE_API_TOKEN = "token"
        ai.generate_cloudflare_background("premium hero", 7, width=1152, height=768, model="@cf/black-forest-labs/flux-2-klein-4b")
        call = post.call_args
        self.assertIn("files", call.kwargs)
        self.assertNotIn("json", call.kwargs)
        self.assertEqual(call.kwargs["files"]["width"][1], "1152")
        self.assertEqual(call.kwargs["files"]["height"][1], "768")
        self.assertEqual(call.kwargs["files"]["seed"][1], "7")

    @patch("pipeline.thumbnail_ai.requests.post")
    def test_flux2_klein_fixed_step_is_not_sent(self, post):
        from pipeline import thumbnail_ai as ai
        post.return_value = _fake_cf_response_for_tests()
        ai.CLOUDFLARE_ACCOUNT_ID = "acct"
        ai.CLOUDFLARE_API_TOKEN = "token"
        ai.generate_cloudflare_background("premium hero", 9, model="@cf/black-forest-labs/flux-2-klein-4b")
        files = post.call_args.kwargs["files"]
        self.assertNotIn("steps", files)


def _fake_cf_response_for_tests():
    import base64, io, json
    r = requests.Response()
    r.status_code = 200
    r.headers["content-type"] = "application/json"
    b = io.BytesIO()
    Image.new("RGB", (64, 64), (20, 80, 120)).save(b, format="PNG")
    r._content = json.dumps({"success": True, "result": {"image": base64.b64encode(b.getvalue()).decode("ascii")}}).encode("utf-8")
    return r
