from __future__ import annotations
import os
import unittest
from unittest.mock import patch

from pipeline import topic_engine as te


class TestTopicSelectionV7(unittest.TestCase):
    def test_exam_only_blocks_non_exam_niche(self):
        plan = {"niche_life": {"voice": {"en": "en-IN"}, "topics": ["Why you wake up exhausted after eight hours"]}}
        state = {"recent_topics": [], "completed_topics": [], "topic_cursors": {}}
        with patch.object(te, "EXAM_ONLY", True), patch.object(te, "ALLOWED_EXAM_NICHES", {"bank_it_officer"}):
            with self.assertRaises(RuntimeError):
                te.choose_best_topic(plan, ["niche_life"], state)

    def test_discovery_order_fields_are_present(self):
        score = te.score_topic("CRR vs SLR: what banks keep as reserves", "banking_awareness", query_signal=4, trend=72)
        self.assertGreaterEqual(score.trend_score, 0)
        self.assertGreaterEqual(score.seo_score, 0)
        self.assertTrue(hasattr(score, "exam_fit"))

    def test_exam_only_niche_fallback_never_returns_lifestyle(self):
        plan = {
            "everyday_life_hacks": {"voice": {"en": "en-IN"}, "topics": ["How to sleep better"]},
            "bank_it_officer": {"voice": {"en": "en-IN"}, "topics": ["TCP 3-way handshake: what SYN, SYN-ACK and ACK actually do"]},
        }
        state = {"recent_topics": [], "completed_topics": [], "topic_cursors": {}}
        with patch.object(te, "EXAM_ONLY", True), patch.object(te, "_candidate_query_signal", return_value=0), patch.object(te, "_trend_scores", return_value={}):
            niche, _, _, topic, _, _ = te.choose_best_topic(plan, ["everyday_life_hacks"], state)
        self.assertEqual(niche, "bank_it_officer")
        self.assertIn("TCP 3-way handshake", topic)

    def test_exam_only_filters_lifestyle_topic_from_exam_niche(self):
        plan = {"bank_it_officer": {"voice": {"en": "en-IN"}, "topics": [
            "Why you wake up exhausted after eight hours of sleep",
            "TCP 3-way handshake: what SYN, SYN-ACK and ACK actually do",
        ]}}
        state = {"recent_topics": [], "completed_topics": [], "topic_cursors": {}}
        with patch.object(te, "EXAM_ONLY", True), patch.object(te, "_candidate_query_signal", return_value=0), patch.object(te, "_trend_scores", return_value={}):
            niche, _, _, topic, _, _ = te.choose_best_topic(plan, ["bank_it_officer"], state)
        self.assertEqual(niche, "bank_it_officer")
        self.assertIn("TCP 3-way handshake", topic)

    def test_selection_board_contains_seo_fields(self):
        score = te.score_topic("CRR vs SLR: what banks keep as reserves", "banking_awareness", query_signal=0, trend=0)
        data = score.as_dict()
        for key in ("search_intent", "seo_fit", "value_density", "exam_fit", "teachability", "visual", "total"):
            self.assertIn(key, data)


    def test_trend_outage_returns_unavailable_signal(self):
        with patch.dict(os.environ, {"TOPIC_USE_TRENDS": "true"}):
            # Stub TrendReq import path to force provider failure without a network call.
            fake = type("BadTrendReq", (), {"__init__": lambda self, *a, **k: (_ for _ in ()).throw(RuntimeError("429"))})
            with patch.dict("sys.modules", {"pytrends.request": type("M", (), {"TrendReq": fake})()}):
                vals = te._trend_scores(["CRR vs SLR"])
        self.assertEqual(vals["CRR vs SLR"], 0.0)

    def test_search_signal_env_can_disable_network(self):
        with patch.dict(os.environ, {"TOPIC_USE_AUTOCOMPLETE": "false"}):
            old = te._candidate_query_signal("TCP handshake")
            self.assertEqual(old, 0.0)

    def test_strong_exam_topic_gets_high_value_score(self):
        score = te.score_topic(
            "SQL GROUP BY vs HAVING: which rows are filtered and when",
            "bank_it_officer",
            query_signal=0,
            trend=0,
        )
        self.assertGreaterEqual(score.teachability, 7.0)
        self.assertGreaterEqual(score.value_density, 7.5)
        self.assertGreaterEqual(score.visual, 5.0)

    def test_risk_language_is_penalized(self):
        good = te.score_topic("SQL GROUP BY vs HAVING: which rows are filtered and when", "bank_it_officer", query_signal=0, trend=0)
        bad = te.score_topic("90% always asked SQL trick guaranteed", "bank_it_officer", query_signal=0, trend=0)
        self.assertGreater(bad.risk_penalty, good.risk_penalty)

    def test_duplicate_recent_topics_are_penalized(self):
        score = te.score_topic("CRR vs SLR", "banking_awareness", recent_topics=["CRR vs SLR"], query_signal=0, trend=0)
        self.assertGreater(score.duplicate_penalty, 0)
        self.assertLess(score.freshness, 5)


# 25 deterministic score checks for representative exam topics.
CASES = [
    ("BCNF vs 3NF in DBMS: the candidate-key condition that decides the answer", "bank_it_officer"),
    ("TCP 3-way handshake: what SYN, SYN-ACK and ACK actually do", "bank_it_officer"),
    ("SQL GROUP BY vs HAVING: which rows are filtered and when", "bank_it_officer"),
    ("Deadlock in OS: the four Coffman conditions with a simple process example", "bank_it_officer"),
    ("Banker Algorithm: how to identify a safe state step by step", "bank_it_officer"),
    ("OSI Layer 3 vs Layer 4: routing versus end-to-end delivery", "bank_it_officer"),
    ("Subnetting shortcut: finding usable hosts without converting everything to binary", "bank_it_officer"),
    ("RSA vs AES: asymmetric versus symmetric encryption with one real use case", "bank_it_officer"),
    ("Machine Input-Output: how shifting positions reveals the operation", "bank_reasoning_quant"),
    ("Percentage to fraction shortcuts that reduce common bank-exam calculations", "bank_reasoning_quant"),
    ("Successive discount: why two discounts cannot simply be added", "bank_reasoning_quant"),
    ("Time and Work: the LCM method with a two-person example", "bank_reasoning_quant"),
    ("Data Interpretation: choosing the correct denominator before calculating", "bank_reasoning_quant"),
    ("CRR vs SLR: what banks keep as reserves and where each reserve sits", "banking_awareness"),
    ("NEFT vs RTGS vs IMPS: how the payment systems differ in purpose and timing", "banking_awareness"),
    ("NPA classification: how the 90-day overdue rule works conceptually", "banking_awareness"),
    ("RBI functions: monetary policy versus currency management", "banking_awareness"),
    ("GDP vs GNP vs NNP: how factor income changes the national-income measure", "rbi_economy"),
    ("Fiscal deficit vs revenue deficit vs primary deficit: where interest payments enter", "rbi_economy"),
    ("Money supply M1 M2 M3: why term deposits appear in broader money", "rbi_economy"),
    ("Monetary policy transmission: how a policy-rate move reaches borrowers", "rbi_economy"),
    ("Subject-verb agreement: why each of takes a singular verb", "bank_english"),
    ("Para jumbles: finding the sentence that must open the paragraph", "bank_english"),
    ("Percentage change: the fastest safe method for SSC arithmetic", "ssc_general"),
    ("Profit and loss: marked price, discount and selling price in one chain", "ssc_general"),
]
for idx, (topic, niche) in enumerate(CASES, 101):
    def make_case(topic=topic, niche=niche):
        def case(self):
            score = te.score_topic(topic, niche, query_signal=0, trend=0)
            self.assertGreater(score.total, 45.0)
            self.assertGreaterEqual(score.teachability, 5.0)
            self.assertGreaterEqual(score.seo_fit, 4.0)
        return case
    setattr(TestTopicSelectionV7, f"test_case_{idx:03d}", make_case())


if __name__ == "__main__":
    unittest.main(verbosity=2)
