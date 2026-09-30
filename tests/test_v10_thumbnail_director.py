from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image, ImageDraw

import pipeline.engagement_v2 as ev2
from pipeline.thumbnail_director import build_brief, build_prompt, detect_text_zone, headline


class TestV10ThumbnailDirector(unittest.TestCase):
    def test_headline_rejects_game_show_copy(self):
        self.assertNotRegex(headline("A OR B?", "CRR vs SLR"), r"A\s+OR\s+B")
        self.assertNotRegex(headline("STOP COUNTDOWN", "NPA classification"), r"STOP|COUNTDOWN")
        self.assertLessEqual(len(headline("A very long headline that should be reduced", "NPA rule").split()), 5)

    def test_briefs_are_materially_different(self):
        briefs = [build_brief("NEFT vs RTGS", "WHICH ROUTE?", "PAYMENT SYSTEMS", i) for i in range(5)]
        self.assertEqual(len({b.visual_metaphor for b in briefs}), 5)
        self.assertEqual(len({b.action for b in briefs}), 5)
        self.assertTrue(all("NO WORDS" not in b.visual_metaphor.upper() for b in briefs))

    def test_prompt_is_image_first(self):
        b = build_brief("CRR vs SLR", "CASH OR ASSETS", "BANKING", 0)
        prompt = build_prompt(b).upper()
        for phrase in ["ONE DOMINANT SUBJECT", "NO WORDS", "NO LOGOS", "LANDSCAPE 16:9"]:
            self.assertIn(phrase, prompt)
        self.assertIn("DO NOT CREATE A LESSON SLIDE", prompt)

    def test_text_zone_chooses_quieter_side(self):
        img = Image.new("RGB", (1280, 720), (20, 20, 20))
        draw = ImageDraw.Draw(img)
        # Busy right half; quiet left half.
        for x in range(700, 1280, 10):
            for y in range(0, 720, 10):
                draw.rectangle((x, y, x + 5, y + 5), fill=(240, 40, 40))
        zone, box, left, right = detect_text_zone(img)
        self.assertEqual(zone, "left")
        self.assertLess(left, right)

    def test_v10_renderer_uses_five_candidates(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bg = Image.new("RGB", (1280, 720), (28, 48, 72))
            # Add a deliberately busy right-side hero area.
            draw = ImageDraw.Draw(bg)
            for x in range(700, 1280, 18):
                draw.line((x, 100, x - 100, 650), fill=(240, 180, 40), width=10)
            bg_path = root / "bg.jpg"
            bg.save(bg_path)
            out = root / "thumbnail.jpg"
            with patch.object(ev2, "_request_ai_background", return_value=None):
                got = ev2.create_custom_thumbnail(
                    root / "video.mp4", out, 0.5, "WHICH ROUTE?", "BANKING",
                    background_path=bg_path, topic="NEFT vs RTGS vs IMPS",
                    variants=5, subline="PAYMENT SYSTEMS",
                )
            self.assertTrue(got.exists())
            self.assertEqual(Image.open(got).size, (1280, 720))
            manifest = (root / "thumbnail_variants" / "manifest.json").read_text()
            self.assertIn('"engine": "v10_creative_director"', manifest)
            import json
            data = json.loads(manifest)
            self.assertEqual(len(data["variants"]), 5)
            self.assertEqual(len(data["creative_briefs"]), 5)


class TestV10TopicOrder(unittest.TestCase):
    def test_trend_is_primary_selector(self):
        from pipeline import topic_engine as te
        plan = {
            "banking_awareness": {"voice": {"en": "en-IN"}, "topics": [
                "CRR vs SLR: where each reserve is kept",
                "NPA classification: how the 90-day overdue rule works",
            ], "weight": 2},
        }
        state = {"recent_topics": [], "completed_topics": [], "last_niche": None, "topic_cursors": {}}
        with patch.object(te, "youtube_suggestions", return_value=[]), patch.object(te, "_trend_scores", return_value={
            plan["banking_awareness"]["topics"][0]: 90.0,
            plan["banking_awareness"]["topics"][1]: 30.0,
        }):
            _, _, _, topic, score, board = te.choose_best_topic(plan, list(plan), state)
        self.assertEqual(topic, plan["banking_awareness"]["topics"][0])
        self.assertEqual(score.trend_score, 100.0)

    def test_low_value_topic_is_not_selected_over_useful_topic(self):
        from pipeline import topic_engine as te
        low = "Banking awareness topic"
        good = "NPA classification: how the 90-day overdue rule works"
        plan = {"banking_awareness": {"voice": {"en": "en-IN"}, "topics": [low, good], "weight": 2}}
        state = {"recent_topics": [], "completed_topics": [], "last_niche": None, "topic_cursors": {}}
        with patch.object(te, "youtube_suggestions", return_value=[]), patch.object(te, "_trend_scores", return_value={low: 100, good: 80}):
            _, _, _, topic, _, _ = te.choose_best_topic(plan, list(plan), state)
        self.assertEqual(topic, good)


if __name__ == "__main__":
    unittest.main()
