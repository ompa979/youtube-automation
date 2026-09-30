from __future__ import annotations

import base64
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests
from PIL import Image

import pipeline.engagement_v2 as ev2
import pipeline.thumbnail_ai as ai


class TestThumbnailHitRateProgram(unittest.TestCase):
    def setUp(self):
        self.old = dict(os.environ)
        self.old_globals = (ai.CLOUDFLARE_ACCOUNT_ID, ai.CLOUDFLARE_API_TOKEN)
        ai.CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")
        ai.CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN", "")
        for key in list(os.environ):
            if key.startswith("CLOUDFLARE_ACCOUNT_ID") or key.startswith("CLOUDFLARE_API_TOKEN") or key == "CLOUDFLARE_MAX_ACCOUNTS":
                os.environ.pop(key, None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.old)
        ai.CLOUDFLARE_ACCOUNT_ID, ai.CLOUDFLARE_API_TOKEN = self.old_globals

    def test_tcp_handshake_copy_is_exact(self):
        h, s = ev2._v11_thumbnail_copy(
            "TCP 3-way handshake: what SYN, SYN-ACK and ACK actually do",
            "What do SYN, SYN-ACK and ACK do?",
            ""
        )
        self.assertEqual(h, "3-WAY HANDSHAKE")
        self.assertEqual(s, "SYN → SYN-ACK → ACK")
        self.assertNotEqual(h, "TCP VS UDP")

    def test_cloudflare_pool_reads_four_accounts(self):
        os.environ["CLOUDFLARE_ACCOUNT_ID"] = "acct1"
        os.environ["CLOUDFLARE_API_TOKEN"] = "tok1"
        os.environ["CLOUDFLARE_ACCOUNT_ID_2"] = "acct2"
        os.environ["CLOUDFLARE_API_TOKEN_2"] = "tok2"
        os.environ["CLOUDFLARE_ACCOUNT_ID_3"] = "acct3"
        os.environ["CLOUDFLARE_API_TOKEN_3"] = "tok3"
        os.environ["CLOUDFLARE_ACCOUNT_ID_4"] = "acct4"
        os.environ["CLOUDFLARE_API_TOKEN_4"] = "tok4"
        os.environ["CLOUDFLARE_MAX_ACCOUNTS"] = "4"
        pool = ai.cloudflare_credential_pool()
        self.assertEqual([x[0] for x in pool], ["1", "2", "3", "4"])
        self.assertEqual([x[1] for x in pool], ["acct1", "acct2", "acct3", "acct4"])

    @patch("pipeline.thumbnail_ai.generate_cloudflare_background")
    def test_cloudflare_failover_moves_after_quota_error(self, generate):
        os.environ["CLOUDFLARE_ACCOUNT_ID"] = "acct1"
        os.environ["CLOUDFLARE_API_TOKEN"] = "tok1"
        os.environ["CLOUDFLARE_ACCOUNT_ID_2"] = "acct2"
        os.environ["CLOUDFLARE_API_TOKEN_2"] = "tok2"
        os.environ["CLOUDFLARE_MAX_ACCOUNTS"] = "2"
        calls = []

        def side_effect(prompt, seed, width, height, model, account_id, api_token):
            calls.append((account_id, model))
            if account_id == "acct1":
                raise RuntimeError("HTTP 429 daily free allocation exhausted")
            return Image.new("RGB", (32, 32), (20, 60, 120))

        generate.side_effect = side_effect
        im, provider = ai.generate_background("hero", 7)
        self.assertEqual(im.size, (32, 32))
        self.assertIn("acct2", provider)
        self.assertEqual(calls[0][0], "acct1")
        self.assertEqual(calls[-1][0], "acct2")

    def test_procedural_handshake_fallback_is_not_portrait_frame(self):
        im = ev2._v11_procedural_hero("TCP 3-way handshake", 0)
        self.assertEqual(im.size, (1280, 720))
        # The fallback has designed color variation and is not a flat image.
        self.assertGreater(max(im.getextrema()[1]) - min(im.getextrema()[1]), 10)

    def test_thumbnail_manifest_records_hit_rate_program(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = root / "thumbnail.jpg"
            bg = root / "bg.jpg"
            Image.new("RGB", (1280, 720), (30, 40, 65)).save(bg)
            video = root / "missing.mp4"
            # AI is disabled in this isolated test so procedural hero fallback is used.
            with patch.object(ev2, "_request_ai_background", return_value=None):
                got = ev2.create_custom_thumbnail(
                    video,
                    out,
                    0.5,
                    "What do SYN, SYN-ACK and ACK do?",
                    "IBPS SO IT",
                    background_path=bg,
                    topic="TCP 3-way handshake: what SYN, SYN-ACK and ACK actually do",
                    variants=5,
                    subline="",
                )
            self.assertTrue(got.exists())
            data = json.loads((root / "thumbnail_variants" / "manifest.json").read_text())
            self.assertEqual(data["thumbnail_patch"], "v17_hit_rate_v2_thumbnail_only")
            self.assertEqual(data["hit_rate_program"], "25-point-thumbnail-hit-rate-program")
            self.assertEqual(data["headline"], "3-WAY HANDSHAKE")
            self.assertEqual(data["subline"], "SYN → SYN-ACK → ACK")
            self.assertEqual(len(data["variants"]), 5)


if __name__ == "__main__":
    unittest.main()
