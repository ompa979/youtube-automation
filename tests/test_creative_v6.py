from __future__ import annotations

import json
import sys
import types
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

# Local test environments may not have google-generativeai installed.
# CI installs requirements.txt, but this stub lets the pure creative contract
# tests run offline without a real Gemini dependency or API call.
try:
    import google.generativeai  # type: ignore  # noqa: F401
except Exception:
    google_mod = types.ModuleType("google")
    genai_mod = types.ModuleType("google.generativeai")
    setattr(google_mod, "generativeai", genai_mod)
    sys.modules.setdefault("google", google_mod)
    sys.modules.setdefault("google.generativeai", genai_mod)

import pipeline.engagement_v2 as ev2
import pipeline.motion_graphics as mg
import pipeline.script_gen as sg
from pipeline.topic_engine import choose_best_topic, score_topic
from pipeline.seo.keyword_clusters import get_cluster_for_topic
from pipeline.seo.seo_score import calculate_seo_score


ROLES = ["hook", "context", "mechanism", "example", "exam_takeaway", "difference_card"]
BANNED = [
    "A OR B", "A) ", "B) ", "QUICK TEST", "THINK FAST", "COUNTDOWN",
    "STOP SCROLLING", "90%", "99%", "ALWAYS ASKED", "SECRET", "GUARANTEED",
]


def make_scene(i: int, role: str, text: str | None = None):
    return SimpleNamespace(
        index=i,
        narration={
            "hook": "M3 is broader than M1 because one extra category is included.",
            "context": "M1 focuses on the most liquid forms of money, while M3 goes wider.",
            "mechanism": "Start with M1, then add the relevant term deposits to understand M3.",
            "example": "Suppose a bank has demand deposits plus term deposits; only the term deposits widen the aggregate.",
            "exam_takeaway": "When a question mentions term deposits, connect that clue with broader money.",
            "difference_card": "M1 is narrower; M3 adds term deposits and is broader.",
        }[role],
        tts_text="same teaching line",
        image_prompt="Premium editorial visual showing the exact mechanism with one clear physical transformation and no text.",
        on_screen_text=text or role.replace("_", " ").upper(),
        card_points=[role.replace("_", " ")],
        action_type=role,
        action_payload="Show the exact teaching mechanism",
        motion_type="push_in",
        camera_motion="push_in",
        sfx_cue="whoosh",
    )


def make_script():
    return SimpleNamespace(
        title="M1 vs M3: Why Term Deposits Expand Money | RBI Grade B",
        hook="M3 is broader than M1 because one extra category is included.",
        description="Learn how M1 and M3 differ and why term deposits make M3 broader. Useful for RBI Grade B revision. #RBIGradeB #Economy #MoneySupply",
        tags=["m1 vs m3", "money supply", "rbi grade b", "economy"],
        pinned_comment="Which part of money supply do you want explained next?",
        scenes=[make_scene(i, r) for i, r in enumerate(ROLES)],
        thumbnail_text="DOES FD EXPAND M3?",
        thumbnail_subline="M1 vs M3",
        thumbnail_visual_prompt="Premium banking scene showing a fixed-deposit certificate flowing into a broader money vault, dramatic depth, right-side hero object, clean left negative space, no text.",
    )


class TestCreativeV6(unittest.TestCase):
    def test_01_prompt_is_value_first(self):
        prompt = sg._build_prompt("Money Supply M1 M3: why term deposits make M3 broader", {
            "system_prompt": "Teach the concept precisely.", "visual_style": "educational_ai"
        }, "en")
        self.assertIn("Every spoken sentence must add information", prompt)
        self.assertIn("MECHANISM", prompt)
        self.assertIn("FINAL DIFFERENCE CARD", prompt)
        self.assertIn("EXAMPLE", prompt)
        self.assertIn("memory", prompt.lower())
        self.assertNotIn("A) [OPTION 1]", prompt.upper())
        self.assertNotIn("3... 2... 1", prompt.upper())
        self.assertIn("NEVER USE", prompt.upper())
        self.assertIn("STOP SCROLLING", prompt.upper())  # appears only inside the forbidden-list instruction

    def test_02_prompt_forbids_filler(self):
        prompt = sg._build_prompt("CRR vs SLR: what banks keep as reserves", {"system_prompt": "Teach clearly."}, "en")
        self.assertIn("never use phrases", prompt.lower())
        for phrase in ["in this video", "keep watching", "stay tuned", "let’s understand"]:
            self.assertIn(phrase, prompt.lower())

    def test_03_to_script_requires_six_scenes(self):
        with self.assertRaises(ValueError):
            sg._to_script({"scenes": []})

    def test_04_roles_are_exact(self):
        s = make_script()
        sg._v6_enforce_contract(s)
        self.assertEqual([x.action_type for x in s.scenes], ROLES)

    def test_05_no_ab_language_survives(self):
        s = make_script()
        s.scenes[1].on_screen_text = "A OR B?"
        s.scenes[1].action_payload = "A) M1 vs B) M3"
        sg._v6_enforce_contract(s)
        joined = " ".join(x.on_screen_text + " " + x.action_payload for x in s.scenes)
        self.assertNotRegex(joined.upper(), r"\bA\s+OR\s+B\b")

    def test_06_thumbnail_copy_short(self):
        self.assertLessEqual(len(make_script().thumbnail_text), 30)

    def test_07_visual_prompt_is_premium(self):
        prompt = ev2._v6_thumb_visual_prompt("Money Supply M1 M3", "DOES FD EXPAND M3", "hero_closeup", "M1 vs M3")
        for phrase in ["PREMIUM", "9:16", "RIGHT", "NO WORDS", "NO LOGOS"]:
            self.assertIn(phrase.upper(), prompt.upper())

    def test_08_thumbnail_renders_offline(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bg = Image.new("RGB", (2160, 3840), (30, 90, 130))
            bg_path = root / "bg.jpg"
            bg.save(bg_path)
            out = root / "thumbnail.jpg"
            with patch.object(ev2, "_request_ai_background", return_value=None):
                got = ev2.create_custom_thumbnail(
                    root / "video.mp4", out, 0.5, "DOES FD EXPAND M3?", "RBI GRADE B",
                    background_path=bg_path, topic="Money Supply M1 M3", variants=3,
                    subline="M1 vs M3", visual_prompt=make_script().thumbnail_visual_prompt,
                )
            self.assertTrue(got.exists())
            with Image.open(got) as im:
                self.assertEqual(im.size, (2160, 3840))
            self.assertTrue((root / "thumbnail_variants" / "manifest.json").exists())

    def test_09_thumbnail_has_no_old_cta_band(self):
        src = Path(ev2.__file__).read_text(encoding="utf-8")
        v6 = src.split("CREATIVE V6 THUMBNAIL ENGINE")[-1]
        self.assertNotIn("QUICK CHALLENGE", v6)

    def test_10_motion_v6_is_minimal(self):
        filt = mg.build_motion_graphics_filter(2.0, "0xFFFFFF", 0, 6, True, "hook", "")
        self.assertIn("drawbox=x=0", filt)
        self.assertNotIn("drawtext", filt.lower())

    def test_11_topic_scoring_penalizes_fake_claims(self):
        clean = score_topic("CRR vs SLR: where each reserve is kept", "banking_awareness", trend=0, query_signal=0)
        risky = score_topic("CRR vs SLR: 90% get this wrong every year", "banking_awareness", trend=0, query_signal=0)
        self.assertGreater(clean.total, risky.total)
        self.assertGreater(risky.risk_penalty, 0)

    def test_12_topic_scoring_rewards_visual_mechanism(self):
        visual = score_topic("TCP handshake: how SYN and ACK move between nodes", "bank_it_officer", trend=0, query_signal=0)
        generic = score_topic("TCP networking topic", "bank_it_officer", trend=0, query_signal=0)
        self.assertGreater(visual.visual, generic.visual)

    def test_13_selector_uses_evidence_board(self):
        plan = {
            "bank_it_officer": {"voice": {"en": "en-IN"}, "topics": ["TCP handshake: how SYN and ACK move", "RSA vs AES: how encryption differs"], "weight": 3},
            "banking_awareness": {"voice": {"en": "en-IN"}, "topics": ["CRR vs SLR: where each reserve is kept", "NPA classification: overdue rule"], "weight": 3},
        }
        state = {"recent_topics": [], "completed_topics": [], "last_niche": None, "topic_cursors": {}}
        with patch("pipeline.topic_engine.youtube_suggestions", return_value=[]), patch("pipeline.topic_engine._trend_scores", return_value={}):
            niche, cfg, lang, topic, score, board = choose_best_topic(plan, list(plan), state)
        self.assertIn(niche, plan)
        self.assertTrue(board)
        self.assertIn(topic, cfg["topics"])
        self.assertEqual(lang, "en")
        self.assertTrue(hasattr(score, "trend_score"))
        self.assertTrue(hasattr(score, "seo_score"))

    def test_14_dynamic_keyword_cluster(self):
        cluster = get_cluster_for_topic("M1 vs M3: why term deposits make M3 broader")
        self.assertIsNotNone(cluster)
        self.assertTrue(cluster.primary_query)

    def test_15_seo_score_accepts_value_first_script(self):
        cluster = get_cluster_for_topic("M1 vs M3: why term deposits make M3 broader")
        s = make_script()
        score = calculate_seo_score(cluster, s.title, s.description, " ".join(x.narration for x in s.scenes), [x.on_screen_text for x in s.scenes], s.tags)
        self.assertGreaterEqual(score.total, 50)

    def test_16_schema_defines_six_scenes(self):
        # Verify the schema that is sent to Gemini is actually V6.
        schema_text = Path(__import__("pipeline.gemini_router", fromlist=["__file__"]).__file__).read_text(encoding="utf-8")
        self.assertIn('"minItems": 6', schema_text)
        self.assertIn('"maxItems": 6', schema_text)
        self.assertIn('"thumbnail_visual_prompt"', schema_text)

    def test_17_render_accepts_thumbnail_visual_prompt(self):
        source = Path("pipeline/render.py").read_text(encoding="utf-8")
        self.assertIn("thumbnail_visual_prompt: str = \"\"", source)
        self.assertIn("visual_prompt=thumbnail_visual_prompt", source)

    def test_18_generate_passes_thumbnail_visual_prompt(self):
        source = Path("pipeline/generate.py").read_text(encoding="utf-8")
        self.assertIn("thumbnail_visual_prompt=getattr(script", source)

    def test_19_generate_entrypoint_is_after_v6_overrides(self):
        source = Path("pipeline/generate.py").read_text(encoding="utf-8")
        self.assertGreater(source.rfind('if __name__ == "__main__"'), source.find("# Runtime overrides used by main/_run_one"))


    def test_21_v6_allows_realistic_100_word_cap(self):
        s = make_script()
        # Expand to a realistic ~90-word teaching script without changing structure.
        extra = " This line adds useful context without changing the concept."
        s.scenes[3].narration += extra + extra
        self.assertIsNone(sg._v6_length_issue(s))

    def test_22_v6_rejects_only_over_100_words(self):
        s = make_script()
        extra = " This adds one more useful sentence to keep the example concrete."
        for scene in s.scenes[:3]:
            scene.narration += extra * 5
        issue = sg._v6_length_issue(s)
        self.assertIsNotNone(issue)
        self.assertIn("hard cap 100", issue)


    def test_23_script_generation_disables_schema_path_in_runtime(self):
        src = Path("pipeline/script_gen.py").read_text(encoding="utf-8")
        self.assertIn("CallType.SCRIPT_GEN, use_schema=False", src)

    def test_20_workflow_is_cloudflare_first(self):
        source = Path(".github/workflows/generate.yml").read_text(encoding="utf-8")
        self.assertIn("CLOUDFLARE_ACCOUNT_ID", source)
        self.assertIn("@cf/black-forest-labs/flux-1-schnell", source)
        self.assertIn("NICHES_ENABLED", source)
        self.assertIn("TOPIC_USE_TRENDS", source)


class TestPromptMatrix(unittest.TestCase):
    pass


# 80 deterministic content-contract cases. These are intentionally varied to catch
# regressions in prompt construction and value-first language without calling Gemini.
_CASES = [
    "BCNF vs 3NF: the exact functional-dependency difference",
    "TCP handshake: how SYN and ACK move",
    "GROUP BY vs HAVING: which filter happens where",
    "Correlated subquery vs JOIN: when the inner query depends on the outer row",
    "Deadlock in operating systems: why circular wait blocks progress",
    "Banker's Algorithm: how the safe-state check works",
    "OSI Layer 3 vs Layer 4: addressing versus delivery",
    "Subnetting: how borrowing host bits changes the network range",
    "RSA vs AES: asymmetric versus symmetric encryption",
    "ACID transactions: why atomicity matters in a failed transfer",
    "Primary key vs candidate key: uniqueness and identification",
    "Firewall vs IDS vs IPS: where detection and blocking happen",
    "CRR vs SLR: where each reserve is maintained",
    "SDF vs reverse repo: how the liquidity tools differ",
    "NEFT vs RTGS vs IMPS: the practical purpose of each rail",
    "NPA classification: how the overdue rule works",
    "Priority Sector Lending: why the category exists",
    "Basel III capital adequacy: what capital protects",
    "Payments Bank vs Small Finance Bank: how the models differ",
    "SARFAESI Act: what the recovery mechanism is designed to do",
    "NABARD vs SIDBI vs NHB: matching institutions to roles",
    "RBI functions: monetary policy versus currency management",
    "KYC vs e-KYC: what changes in verification",
    "PCA framework: how supervisory restrictions escalate",
    "M1 vs M3: why term deposits broaden money",
    "GDP vs GNP vs NNP: how factor income changes the measure",
    "Demand-pull vs cost-push inflation: what changes after an oil shock",
    "Fiscal deficit vs revenue deficit vs primary deficit",
    "Current account vs capital account: where trade and investment flows belong",
    "FRBM rules: why escape clauses exist",
    "MPC voting: how the policy-rate decision is made",
    "RBI vs SEBI vs IRDAI: who regulates what",
    "Monetary policy transmission: how a rate change reaches borrowers",
    "Financial inclusion: what a basic bank account is for",
    "Machine input-output: how the transformation chain works",
    "Syllogism: how to separate only-a-few from few",
    "Blood relations: how to map a family chain without guessing",
    "Circular seating: how to lock one reference position",
    "Quadratic equations: what the discriminant tells you",
    "Inequalities: how sign changes affect the solution",
    "Number series: how to test differences before ratios",
    "Percentage change: how to avoid the base-value trap",
    "Successive discount: why percentages multiply instead of simply add",
    "Time and work: why LCM is useful for combined rates",
    "Data interpretation: how to choose the correct denominator",
    "Coding-decoding: how to identify the transformation pattern",
    "Subject-verb agreement: why each of takes a singular verb",
    "One of the: why the verb is singular",
    "Para jumbles: finding the sentence that must open the paragraph",
    "Cloze tests: how context narrows the blank",
    "Reading comprehension: how to eliminate inference traps",
    "Dangling modifiers: how one sentence becomes ambiguous",
    "Prepositions: choosing collocations instead of translation",
    "Word rearrangement: using sentence anchors",
    "Synonyms and antonyms: using roots to narrow unfamiliar words",
    "Indian Constitution: Fundamental Rights versus Directive Principles",
    "Indian monsoon: why the winds reverse seasonally",
    "Modern history: trigger versus background cause",
    "Percentage arithmetic: the fastest safe setup",
    "Ratio and proportion: scaling a mixture",
    "Relative speed: why the closing-speed formula changes",
    "Profit and loss: marked price to selling price in one chain",
    "Static GK: separating location, river and state facts",
    "Zero Trust: why identity is checked before access",
    "Hashing vs encryption: what the output means",
    "SQL WHERE vs HAVING: row filter versus group filter",
    "Indexes: why reads get faster and writes can get slower",
    "Normalization: why repeating groups create update anomalies",
    "DNS resolution: how a domain becomes an IP address",
    "HTTPS: what TLS adds to an ordinary HTTP request",
    "Caching: why repeated reads can avoid database work",
    "Load balancing: how traffic is spread across servers",
    "Virtual memory: why pages move between RAM and disk",
    "Paging vs segmentation: how memory is divided",
    "Process vs thread: what each execution unit owns",
    "CPU scheduling: why turnaround and response time differ",
    "Normalization 2NF: removing partial dependency",
    "Normalization 3NF: removing transitive dependency",
    "Deadlock prevention: how breaking one Coffman condition helps",
    "Public key cryptography: which key encrypts and which decrypts",
    "API authentication: token versus session concepts",
    "HTTP methods: why GET and POST are not interchangeable",
]


def _make_contract_case(i, topic):
    def test(self):
        prompt = sg._build_prompt(topic, {
            "system_prompt": "Teach one complete exam-relevant concept with a concrete example.",
            "visual_style": "educational_ai",
        }, "en")
        upper = prompt.upper()
        self.assertIn("ONE COMPLETE IDEA", upper)
        self.assertIn("MECHANISM", upper)
        self.assertIn("EXAMPLE", upper)
        self.assertIn("EXAM TAKEAWAY", upper)
        self.assertIn("FINAL DIFFERENCE CARD", upper)
        self.assertNotIn("A) [OPTION 1]", upper)
        self.assertNotIn("3... 2... 1", upper)
        self.assertNotIn("STOP. 🚨", upper)
        self.assertGreaterEqual(len(prompt), 1800)
    return test


for idx, topic in enumerate(_CASES, start=21):
    setattr(TestPromptMatrix, f"test_case_{idx:03d}", _make_contract_case(idx, topic))


if __name__ == "__main__":
    unittest.main(verbosity=2)
