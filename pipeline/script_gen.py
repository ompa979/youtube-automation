"""Natural Indian-English educational script generation — v19 three-pass pipeline.

Model routing is handled by GeminiRouter (pipeline/gemini_router.py):

  TIER 2  Flash Lite — gemini-3.5/3.1-flash-lite  (500 RPD each)
  TIER 3  Gemma 4   — gemma-4-26b / gemma-4-31b  (14,400 RPD each)

Three-pass generation per video (~4-6 Gemini calls):
  Pass 1  SCRIPT_GEN  → gemini-3.5-flash-lite, thinking=high, schema-constrained
                         (hard-enforces ≤5 scenes; eliminates most repair calls)
  Pass 2  FACT_CHECK  → gemini-3.1-flash-lite (cross-model!), thinking=high
                         BLOCKING: issues → repair → ScriptRejected
  Pass 3  POLISH      → gemini-3.1-flash-lite, thinking=medium (hook + pacing)
  SEO     SEO         → gemini-3.5-flash-lite, thinking=low (title/desc/tags)

v19 changes on top of v18:
  - Two Flash-Lite models: 3.5 drafts, 3.1 fact-checks + polishes (cross-model)
  - Schema-constrained output: response_schema enforces ≤5 scenes, required fields
  - thinking_config per call type: 8192/8192/2048/512/0 tokens
  - POLISH pass: third Gemini call checks hook (first 3s) and pacing
  - Word budget tightened: 55-85 words (28-34s), from 45-80 (20-30s)
  - Prompt updated: pacing shape rule, mnemonic hint, 5-scene hard limit stated

Also provides:
  - seo_optimize_all(): one Gemini call for title + description + tags
  - fact_check_script(): cross-model factual accuracy pass
  - polish_script(): hook + pacing review pass
  - Hook image rule: scene 0 always a striking single-subject visual
  - Hook STYLE rotation (question / shocking-fact / numbered)
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, asdict, field

from .gemini_router import GeminiRouter, CallType
# POLISH is the third pass — hook + pacing review after fact-check
from .quality import validate_script
from .subject_area import classify_subject_area
from .seo import (
    get_cluster_for_topic,
    generate_seo_title, pick_title_mode, extract_problem_hook, TitleMode,
    generate_v3_description, generate_v3_tags,
    validate_keyword_density, auto_repair_narration, auto_repair_screen_text,
    calculate_seo_score, calculate_retention_score, calculate_final_publish_score,
)


# Backwards-compat shim so any external code that does
#   from .script_gen import _generate_gemini
# still gets something callable.  New code should use GeminiRouter directly.
def _generate_gemini(prompt: str, api_key: str, model_name: str | None = None) -> str:
    """Deprecated shim — routes through GeminiRouter.SCRIPT_GEN."""
    router = GeminiRouter(api_key=api_key)
    return router.generate(prompt, call_type=CallType.SCRIPT_GEN)


def _stable_hash(text: str) -> int:
    """Deterministic hash so the same topic always rotates to the same hook
    style (reproducible repairs/retries), while different topics differ."""
    return int(hashlib.md5(text.encode("utf-8")).hexdigest(), 16)


# #7 Hook style rotation — picked once per topic so the opening line style
# varies across videos instead of every script reaching for the same pattern.
_HOOK_STYLES = {
    "question": (
        "Open the very first spoken line as a genuine question the viewer "
        "would actually wonder about — not a rhetorical setup, a real question."
    ),
    "shocking_fact": (
        "Open the very first spoken line with a surprising, counter-intuitive "
        "fact stated directly as a statement (no question mark)."
    ),
    "numbered": (
        "Open the very first spoken line around a short number cue (for example "
        "'Two things decide this...' or 'One invisible factor...'), stated "
        "naturally — not a clickbait numbered-listicle tone."
    ),
}


def _pick_hook_style(topic: str) -> str:
    keys = list(_HOOK_STYLES)
    return keys[_stable_hash(topic) % len(keys)]


class ScriptRejected(RuntimeError):
    """Script failed fact-check / QA after the repair pass. Never publish it;
    the caller should skip the topic (not retry it forever)."""


@dataclass
class Scene:
    index: int
    narration: str
    tts_text: str
    image_prompt: str
    on_screen_text: str
    card_points: list[str] = field(default_factory=list)
    action_type: str = "explanation"
    action_payload: str = ""
    motion_type: str = ""
    camera_motion: str = ""
    sfx_cue: str = ""


@dataclass
class Script:
    title: str
    hook: str
    description: str
    tags: list[str]
    scenes: list[Scene]
    pinned_comment: str = ""
    seo_metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "pinned_comment": self.pinned_comment,
            "title": self.title,
            "hook": self.hook,
            "description": self.description,
            "tags": self.tags,
            "scenes": [asdict(s) for s in self.scenes],
        }


def _build_prompt(
    topic: str,
    niche_cfg: dict,
    language: str,
    repair: str | None = None,
    hook_style: str | None = None,
) -> str:
    hook_style = hook_style or _pick_hook_style(topic)
    hook_instruction = _HOOK_STYLES[hook_style]

    lang_instruction = """
Write the viewer-facing narration in SIMPLE, clear, natural conversational Indian English,
aimed at Indian viewers (school/exam-going audience, general public — not native-English
academics). Concretely:
- Prefer short sentences (roughly 8-14 words) over long compound ones.
- Prefer everyday words over uncommon/formal vocabulary (e.g. "use" not "utilize",
  "show" not "demonstrate", "because" not "owing to") — never at the cost of accuracy.
- Use an Indian English speaking style: natural rhythm, familiar Indian examples where
  useful, but do NOT use Hinglish, Roman Hindi, Devanagari, or forced Indian slang.
- Keep necessary technical/exam terms in standard English and briefly explain them in
  plain words the first time they appear, instead of assuming the viewer already knows them.
The `tts_text` must be the same English spoken content, optimized specifically for natural,
calm Indian-educator pronunciation and cadence:
- Use commas generously to force natural breathing pauses between thoughts and clauses.
- Write technical terms and acronyms spaced out with commas for crisp articulation (e.g. "I B P S, S O, I T", "1 N F", "number 1").
- Do not cram multiple dense ideas into a single sentence. Speak with clarity, calm authority, and patience.
""".strip()

    repair_text = f"\nREPAIR REQUEST:\n{repair}\n" if repair else ""
    card_rules = ""
    if niche_cfg.get("visual_style") == "text_card":
        card_rules = """
TEXT-CARD CHANNEL (curiosity-first, decluttered layout):
- Every scene is shown as a sleek, decluttered visual card.
- `card_points`: Exactly ONE high-impact memory anchor or cheat rule (max 6 words, e.g. ["3NF: KILL TRANSITIVE DEPENDENCY"]).
  NEVER provide multiple long bullet points. Keep it punchy so the screen breathes and viewers focus on the animated captions.
- `on_screen_text`: a 1-3 word high-curiosity headline or cue (e.g. "3-SEC TRICK", "EXAM TRAP", "1NF vs 2NF", "CAN YOU SOLVE?").
- `image_prompt` can be a short placeholder such as "text card".
""".strip()
    elif niche_cfg.get("visual_style") == "cinematic_hud":
        card_rules = """
CINEMATIC HUD CHANNEL (photorealistic AI visuals + animated motion graphics):
- Every scene has a FULL-BLEED dramatic AI background image + animated Ken Burns motion + glowing HUD overlays.
- `image_prompt`: CRITICAL — write a vivid, dark-cinematic visual concept (20-40 words) that DEPICTS the mechanism being explained.
  Examples:
    • For BCNF/3NF: "glowing holographic relational database table with neon arrows showing functional dependency, dark background, cyberpunk server room"
    • For TCP SYN-ACK: "neon laser beam handshake between two holographic server nodes, deep space dark background, volumetric light"
    • For NPA 90-day: "cracked vault door with glowing red countdown timer, dramatic cinematic lighting, dark banking hall"
    • For Syllogism: "glowing Venn diagram laser projection, midnight dark background, volumetric God rays"
  The image MUST visually represent the concept — NOT a generic "education" stock image.
  DO NOT use text, labels, watermarks, or logos in the image prompt.
- `on_screen_text`: a 1-3 word HIGH-CURIOSITY headline or memory cue (e.g. "3-SEC TEST", "EXAM TRAP", "90-DAY RULE", "CAN YOU SOLVE?").
- `card_points`: Exactly ONE punchy memory anchor (max 6 words, e.g. ["BCNF = NO PARTIAL KEY"]).
""".strip()

    topic_lock = (
        "TOPIC LOCK: the title, hook and every scene must be about exactly this topic. "
        "The title must contain the topic's main keywords (and the exam name if the topic names one). "
        "Do not switch to a different topic."
    )
    return f"""
{niche_cfg.get('system_prompt', '')}

You are an elite viral educational Shorts creator and interactive challenge designer.

{lang_instruction}

TOPIC: {topic}
{topic_lock}
{card_rules}

🔥 "SEXY SHORTS ENGINE V2" INTERACTIVE CHALLENGE ARCHITECTURE (MANDATORY):
Do NOT create a passive lecture or study card ("Here is an educational fact. Please watch me explain it.").
Make the viewer actively PLAY A GAME in the video!

Target: EXACTLY 5 or 6 fast scenes (45-65 total words across the entire Short, 18-24 seconds total).
Each scene must perform an exact psychological function:

Scene 0 (0-2s) — PATTERN INTERRUPT:
- Spoken line MUST start with an explosive pattern interrupt: "STOP. 🚨", "WAIT.", "You are about to make a huge mistake.", or an aggressive contradiction.
- `action_type`: "pattern_interrupt"
- `action_payload`: "STOP. 🚨"
- `on_screen_text`: "STOP 🚨"
- `card_points`: ["TRAP DETECTED"]
- `image_prompt`: action visual: [object] + [action] + [contrast]

Scene 1 (2-5s) — THE CHALLENGE / QUESTION:
- Force the viewer to guess: "Which one does X? A or B?", "Where does this belong?"
- `action_type`: "challenge"
- `action_payload`: "A) [Option 1]  vs  B) [Option 2]"
- `on_screen_text`: "A OR B?"
- `card_points`: ["A) [Option 1]  |  B) [Option 2]"]

Scene 2 (5-7s) — COUNTDOWN & TENSION:
- Build tension: "3... 2... 1... Think fast!", "Don't answer yet!"
- `action_type`: "countdown"
- `action_payload`: "3... 2... 1..."
- `on_screen_text`: "3... 2... 1..."
- `card_points`: ["THINK FAST"]

Scene 3 (7-11s) — THE REVEAL & REJECTION:
- Reveal the answer AND reject the wrong answer: "[Correct]! [Wrong] is completely wrong. But why?"
- `action_type`: "reveal"
- `action_payload`: "[Wrong] ❌  |  [Correct] ✅"
- `on_screen_text`: "REVEAL!"
- `card_points`: ["[Wrong] ❌  |  [Correct] ✅"]

Scene 4 (11-16s) — THE MECHANISM / EQUATION:
- Show the visual equation or mechanism: "Here is why: X does this, but Y does that."
- `action_type`: "mechanism"
- `action_payload`: "[INPUT 1] + [INPUT 2] → [RESULT]"
- `on_screen_text`: "THE TRICK"
- `card_points`: ["[INPUT 1] + [INPUT 2] → [RESULT]"]

Scene 5 (16-21s) — EXAM TRAP & SEAMLESS LOOP:
- The exam trap + comment CTA: "The trap? Exams test if you confuse X with Y. Did you guess A or B? Comment below, because..."
- `action_type`: "loop"
- `action_payload`: "👇 A OR B?"
- `on_screen_text`: "DID YOU WIN?"
- `card_points`: ["COMMENT: A OR B?"]
- The last words must seamlessly lead back into Scene 0 ("STOP.")!

VISUAL RULES:
- `image_prompt`: Follow [object] + [action] + [destination/contrast], dark cinematic lighting, vertical 9:16, no text or labels.
- On-screen text: 1-3 word high-curiosity headline.

Return EXACTLY this JSON shape (no markdown):
{{
  "title": "clear title, under 80 chars, accurate, no fake clickbait",
  "hook": "the first spoken line",
  "description": "2-3 useful sentences with 3 relevant hashtags",
  "pinned_comment": "one short question that invites a comment reply (e.g. 'Did you guess A or B? Comment below!')",
  "tags": ["8-12 lowercase tags"],
  "scenes": [
    {{
      "action_type": "pattern_interrupt | challenge | countdown | reveal | mechanism | loop",
      "action_payload": "short cue string for HUD overlay",
      "narration": "natural fast-paced spoken line",
      "tts_text": "same English spoken line optimized with commas for natural TTS breath pauses",
      "image_prompt": "action-oriented visual prompt: [object] + [action] + [destination], vertical 9:16, no text",
      "on_screen_text": "1-3 word curiosity cue",
      "card_points": ["ONE punchy memory anchor line, max 6 words"]
    }}
  ]
}}

Use exactly 5 or 6 scenes. Total word count across all scenes must be between 45 and 65 words.
{repair_text}
""".strip()


def _extract_json_candidates(raw: str) -> list[str]:
    text = (raw or "").strip()
    candidates: list[str] = []
    for match in re.finditer(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.I | re.S):
        block = match.group(1).strip()
        if block.startswith("{") and block.endswith("}"):
            candidates.append(block)
    for start in [m.start() for m in re.finditer(r"\{", text)]:
        depth = 0
        in_string = False
        escaped = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(text[start:i + 1].strip())
                    break
    first = text.find("{")
    last = text.rfind("}")
    if first >= 0 and last > first:
        candidates.append(text[first:last + 1])
    unique: list[str] = []
    seen: set[str] = set()
    for c in candidates:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    return unique


def _remove_trailing_commas(text: str) -> str:
    out: list[str] = []
    in_string = False
    escaped = False
    i = 0
    while i < len(text):
        ch = text[i]
        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == ",":
            j = i + 1
            while j < len(text) and text[j].isspace():
                j += 1
            if j < len(text) and text[j] in "}]":
                i += 1
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def _parse_json(raw: str) -> dict:
    candidates = _extract_json_candidates(raw)
    if not candidates:
        raise ValueError(f"No JSON object found in LLM output:\n{(raw or '')[:800]}")
    errors: list[str] = []
    for candidate in candidates:
        try:
            value = json.loads(candidate)
            if isinstance(value, dict):
                return value
            errors.append("JSON root was not an object")
        except json.JSONDecodeError as exc:
            errors.append(f"line {exc.lineno} col {exc.colno}: {exc.msg}")
            try:
                value = json.loads(_remove_trailing_commas(candidate))
                if isinstance(value, dict):
                    return value
            except json.JSONDecodeError:
                pass
    raise ValueError(
        "Gemini returned invalid JSON: " + " | ".join(errors[:4])
        + f"\nRAW:\n{(raw or '')[:1200]}"
    )





def _first_text(raw: dict, *keys: str) -> str:
    for key in keys:
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _to_script(data: dict) -> Script:
    raw_scenes = data.get("scenes")
    if not isinstance(raw_scenes, list) or not raw_scenes:
        raise ValueError("Generated script contains no scenes")

    scenes: list[Scene] = []
    for i, raw in enumerate(raw_scenes):
        if not isinstance(raw, dict):
            raise ValueError(f"Scene {i + 1} is not an object")

        narration = _first_text(raw, "narration", "voiceover", "voice_over",
                                 "spoken_text", "speech", "dialogue", "text", "script")
        tts_text = _first_text(raw, "tts_text", "tts", "voice_text", "voiceover",
                                "voice_over", "narration", "spoken_text", "speech",
                                "dialogue", "text", "script")

        if not narration and tts_text:
            narration = tts_text
        if not tts_text and narration:
            tts_text = narration

        if not narration:
            raise ValueError(
                f"Generated scene {i + 1} has no usable narration/tts text. "
                f"Available fields: {sorted(raw.keys())}"
            )
        if any("\u0900" <= ch <= "\u097F" for ch in narration + tts_text):
            raise ValueError(f"Generated scene {i + 1} contains Devanagari/Hindi text; English-only required")

        image_prompt = _first_text(raw, "image_prompt", "visual_prompt", "visual", "image", "prompt")
        if not image_prompt:
            image_prompt = (
                "A fresh handwritten study-notes composition that visually explains the narration "
                "with hand-drawn diagrams, arrows, circles and selective handwritten labels."
            )

        # Optimization #2: force scene 0 to always be a striking hook image
        if i == 0 and "stop someone scrolling" not in image_prompt:
            image_prompt = (
                "Ultra-striking hook visual: " + image_prompt
                + ", single dramatic subject, extreme contrast, visually arresting composition "
                "that stops a viewer mid-scroll, cinematic lighting, vertical 9:16"
            )

        on_screen_text = _first_text(raw, "on_screen_text", "caption", "keyword", "memory_cue")
        raw_points = raw.get("card_points") or raw.get("points") or []
        if isinstance(raw_points, str):
            raw_points = [raw_points]
        card_points = [" ".join(str(x).split())[:70] for x in raw_points if str(x).strip()][:3]

        action_type = _first_text(raw, "action_type", "type", "purpose", "scene_type").lower()
        if not action_type or action_type not in (
            "pattern_interrupt", "challenge", "countdown", "reveal", "mechanism", "trap", "loop"
        ):
            if i == 0:
                action_type = "pattern_interrupt"
            elif i == 1:
                action_type = "challenge"
            elif i == 2:
                action_type = "countdown"
            elif i == 3:
                action_type = "reveal"
            elif i == 4:
                action_type = "mechanism"
            elif i >= 5:
                action_type = "trap" if i == 5 and len(raw_scenes) > 6 else "loop"

        action_payload = _first_text(raw, "action_payload", "payload", "cue", "detail")

        motion_type = _first_text(raw, "motion_type", "motion", "animation")
        camera_motion = _first_text(raw, "camera_motion", "camera", "cam_motion")
        sfx_cue = _first_text(raw, "sfx_cue", "sfx", "sound_cue")

        if not motion_type:
            motion_type = {
                "pattern_interrupt": "slam_impact",
                "challenge": "split_doors",
                "countdown": "countdown_321",
                "reveal": "winner_reveal",
                "mechanism": "formula_build",
                "trap": "contrast_split",
                "loop": "comment_quiz",
            }.get(action_type, "slam_impact")

        if not camera_motion:
            camera_motion = {
                "pattern_interrupt": "shake_and_push",
                "challenge": "snap_zoom",
                "countdown": "push_fast",
                "reveal": "snap_zoom",
                "mechanism": "pan_subtle",
                "trap": "pan_subtle",
                "loop": "push_in",
            }.get(action_type, "push_in")

        if not sfx_cue:
            sfx_cue = {
                "pattern_interrupt": "boom",
                "challenge": "whoosh",
                "countdown": "tick",
                "reveal": "chime",
                "mechanism": "whoosh",
                "trap": "alert",
                "loop": "whoosh",
            }.get(action_type, "whoosh")

        scenes.append(Scene(
            index=i,
            narration=narration,
            tts_text=tts_text,
            image_prompt=image_prompt,
            on_screen_text=on_screen_text.upper(),
            card_points=card_points,
            action_type=action_type,
            action_payload=action_payload,
            motion_type=motion_type,
            camera_motion=camera_motion,
            sfx_cue=sfx_cue,
        ))

    return Script(
        title=str(data.get("title", "")).strip(),
        hook=str(data.get("hook", "")).strip(),
        description=str(data.get("description", "")).strip(),
        tags=[str(t).lower().lstrip("#") for t in data.get("tags", [])][:15],
        scenes=scenes,
        pinned_comment=str(data.get("pinned_comment", "")).strip(),
    )


# #7 Hashtag safety net — Gemini is asked for hashtags in the description,
# but LLM compliance isn't guaranteed. This guarantees at least 3 relevant
# hashtags always ship, without duplicating whatever Gemini already added.
HASHTAG_POOL: dict[str, list[str]] = {
    "exam_concepts": ["#UPSC", "#NEET", "#SSC", "#IndiaGK", "#ExamPrep"],
    "science_explainers": ["#ScienceFacts", "#Physics", "#Chemistry", "#Biology", "#LearnOnYoutube"],
    "default": ["#Shorts", "#LearnSomethingNew", "#DidYouKnow"],
}


def _ensure_hashtags(description: str, topic: str, niche_key: str | None) -> str:
    existing = re.findall(r"#\w+", description)
    if len(existing) >= 3:
        return description
    pool = _SEO_HASHTAGS_BY_NICHE.get(niche_key or "") or _SEO_HASHTAGS_BY_SUBJECT_AREA.get(
        classify_subject_area(topic), HASHTAG_POOL.get(niche_key or "", HASHTAG_POOL["default"])
    )
    existing_lower = {e.lower() for e in existing}
    to_add = [h for h in pool if h.lower() not in existing_lower][: 3 - len(existing)]
    if not to_add:
        return description
    return description.rstrip() + "\n\n" + " ".join(to_add)


_SEO_HASHTAGS_BY_NICHE = {
    "bank_it_officer": ["#shorts", "#ibpssoit", "#bankexams", "#itofficer", "#examprep"],
    "bank_reasoning_quant": ["#shorts", "#bankpo", "#reasoning", "#quantaptitude", "#ibpspo"],
    "banking_awareness": ["#shorts", "#bankingawareness", "#bankexams", "#sbipo", "#rbi"],
    "rbi_economy": ["#shorts", "#rbigradeb", "#economy", "#bankexams", "#monetarypolicy"],
    "bank_english": ["#shorts", "#bankexams", "#englishforbankexams", "#ibpspo", "#sbipo"],
    "why_things_work": ["#shorts", "#didyouknow", "#sciencefacts", "#amazingfacts", "#learnonshortsm"],
    "exam_concepts":   ["#shorts", "#upsc", "#examprep", "#studymotivation", "#currentaffairs"],
    "science_explainers": ["#shorts", "#science", "#sciencefacts", "#physics", "#biology"],
    "india_facts":     ["#shorts", "#india", "#indiafacts", "#incredibleindia", "#indianhistory"],
    "mind_and_body":   ["#shorts", "#brainfacts", "#health", "#psychology", "#studytips"],
}

# Keyed by the topic's actual *subject area* (from classify_subject_area),
# not by which content_plan.json niche bucket the video happened to be
# rotated into. This is the correct signal to hang hashtags off of: when
# Google Trends substitutes an off-niche trending topic (e.g. a banking
# story landing in the "why_things_work" rotation slot), the niche-keyed
# pool above would hand back #sciencefacts on a banking video — which is
# exactly the bug reported (bank-passbook video tagged #sciencefacts
# #amazingfacts #learnonshortsm). subject_area is derived from the topic
# text itself, so it tracks what the video is actually about regardless
# of rotation. Falls back to the niche-keyed pool only for "default"
# (no keyword match at all).
_SEO_HASHTAGS_BY_SUBJECT_AREA = {
    "geography": ["#shorts", "#geography", "#indiafacts", "#didyouknow", "#mapfacts"],
    "history": ["#shorts", "#history", "#indianhistory", "#didyouknow", "#incredibleindia"],
    "science": ["#shorts", "#sciencefacts", "#didyouknow", "#physics", "#biology"],
    "economy": ["#shorts", "#economy", "#bankingawareness", "#examprep", "#financefacts"],
    "psychology": ["#shorts", "#brainfacts", "#psychology", "#didyouknow", "#studytips"],
    "india": ["#shorts", "#india", "#indiafacts", "#incredibleindia", "#didyouknow"],
}


# ═════════════════════════════════════════════════════════════════════════════
# v18 — channel-audit enforcement layer (deterministic; does not trust the LLM)
# ═════════════════════════════════════════════════════════════════════════════

# ── #4 Duration — only enforce YouTube's 60s Shorts hard limit.
# No artificial word ceiling: quality and completeness matter more than
# hitting an arbitrary time target.  A 45s Short that teaches well beats
# a 28s Short that had to cut the key example.
# At 2.5 words/sec, 60s = 150 words.  Leave 10 words of buffer → 140 max.
MIN_WORDS = 40           # floor: must teach at least one idea
MAX_WORDS = 140          # ceiling: YouTube Shorts hard limit (~56 s)


def _length_issue(script: "Script") -> str | None:
    words = sum(len(s.narration.split()) for s in script.scenes)
    if words > MAX_WORDS:
        return (f"narration is {words} words (~{words / 2.5:.0f}s); "
                f"YouTube Shorts must be under 60s — cut the least essential scene")
    if words < MIN_WORDS:
        return f"narration only {words} words — needs at least {MIN_WORDS} words to teach one complete idea"
    return None


# ── #1 Comment CTA
_CTA_PATTERN = re.compile(
    r"\b(comment|type (?:your|a|b|c|d)|tell me (?:below|in)|drop (?:your|a)|reply|"
    r"let me know (?:below|in)|write (?:your|down))\b", re.I)

_DEFAULT_CTAS = [
    "Comment your answer below.",
    "Which option did you pick? Comment below.",
    "Comment your exam date, I will reply.",
]


def _has_cta(text: str) -> bool:
    return bool(_CTA_PATTERN.search(text or ""))


def _build_content_aware_pinned_comment(topic: str, script: "Script") -> str:
    """Generate a content-aware pinned comment tailored to the topic (not generic A/B)."""
    topic_l = topic.lower()
    all_narr = " ".join(s.narration for s in script.scenes).lower()

    if any(k in topic_l for k in ("charge", "fee", "money", "savings", "bank account", "hidden")):
        return "💸 Which hidden bank charge surprised you the most?\n\nA️⃣ Minimum balance fee\nB️⃣ SMS / alert charges\nC️⃣ ATM usage fee\nD️⃣ Annual card fee\n\n👇 Comment below — have you ever noticed unexpected deductions?"
    if any(k in topic_l for k in ("ai", "tool", "phone", "setting", "privacy", "hack", "secret")):
        return "⚡ Did you know about this trick before watching?\n\nYES 🤯 or NO 👇\n\nComment your favorite tech tool below!"
    if any(k in topic_l for k in ("rule", "trick", "shortcut", "difference", "vs", "versus")):
        # Check if the scene actually had an A vs B challenge
        if "option a" in all_narr or "a or b" in all_narr:
            return "🎯 Did you guess option A or option B? Comment your answer below!"
        return "💡 Have you solved a question on this before? Share your exam trick in the comments below!"
    return "👇 What did you think of this? Drop your thoughts or questions in the comments below!"


def _ensure_cta(script: "Script", topic: str) -> None:
    """Guarantee the last scene asks for a comment, the description carries the
    CTA, and a content-aware pinned_comment exists."""
    last = script.scenes[-1]
    if not _has_cta(last.narration):
        cta = _DEFAULT_CTAS[_stable_hash(topic) % len(_DEFAULT_CTAS)]
        last.narration = last.narration.rstrip() + " " + cta
        last.tts_text = last.tts_text.rstrip() + " " + cta
        print(f"[cta] LLM omitted comment CTA — appended: {cta!r}")

    # If pinned_comment is missing or contains generic/mismatched A/B when no A/B was in the video:
    all_narr = " ".join(s.narration for s in script.scenes).lower()
    has_ab = "option a" in all_narr or "a or b" in all_narr or "a)" in all_narr
    if not script.pinned_comment or ("a or b" in script.pinned_comment.lower() and not has_ab):
        script.pinned_comment = _build_content_aware_pinned_comment(topic, script)
        print(f"[cta] generated content-aware pinned comment: {script.pinned_comment[:60]}...")

    if not _has_cta(script.description):
        script.description = script.description.rstrip() + "\n\n" + script.pinned_comment


# ── #2 Known factual-error guard (runs even if the LLM fact-check is down)
_KNOWN_FACT_ERRORS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bCEO of (?:the )?(?:RBI|Reserve Bank)", re.I),
     "RBI has a Governor, not a CEO"),
    (re.compile(r"\bRBI\s+CEO\b", re.I), "RBI has a Governor, not a CEO"),
    (re.compile(r"\bShaktikanta Das\b", re.I),
     "do not name RBI office-holders (Das's term ended Dec 2024) — refer to 'the RBI Governor'"),
    (re.compile(r"\b(?:Governor|Chairman|CEO|MD|Finance Minister)\s+(?:is|was)\s+[A-Z][a-z]+ [A-Z][a-z]+"),
     "names a current office-holder — refer to the post, not the person"),
    (re.compile(r"\bSBI\s+(?:CEO|Governor)\b", re.I),
     "SBI has a Chairman, not a CEO/Governor"),
]


def _known_fact_issues(script: "Script") -> list[str]:
    body = " ".join([script.title, script.hook, script.description]
                    + [s.narration for s in script.scenes])
    return [msg for pat, msg in _KNOWN_FACT_ERRORS if pat.search(body)]


# ── #5 Exam name in title
_NON_EXAM_NICHES = {
    "money_wealth_hacks",
    "ai_tech_hacks",
    "science_curiosity",
    "everyday_life_hacks",
    "why_things_work",
    "india_facts",
    "mind_and_body",
}

# Only true exam-prep niches have default exam associations
_EXAM_BY_NICHE = {
    "bank_it_officer": "IBPS SO IT",
    "bank_reasoning_quant": "SBI PO",
    "bank_english": "IBPS PO",
}

_EXAM_RE = re.compile(
    r"\b(IBPS\s*(?:SO(?:\s*IT)?|PO|Clerk|RRB)|SBI\s*(?:PO|Clerk|SO)|RBI\s*(?:Grade\s*B|Assistant)|"
    r"NABARD|SEBI|IFSC|LIC\s*AAO|GATE|UPSC|SSC|NEET)\b", re.I)
TITLE_MAX = 85


def _exam_for(topic: str, niche_key: str | None) -> str | None:
    """Return exam name ONLY if the topic itself is about an exam or the niche is an exam-prep niche."""
    if niche_key in _NON_EXAM_NICHES:
        return None
    m = _EXAM_RE.search(topic or "")
    if m:
        return re.sub(r"\s+", " ", m.group(1)).upper().replace("RBI GRADE B", "RBI Grade B")
    # For banking_awareness and rbi_economy, only attach exam if the topic has exam cues
    if niche_key in ("banking_awareness", "rbi_economy"):
        if re.search(r"\b(exam|exams|aspirant|mains|prelims|cutoff|paper|mcq|syllabus)\b", topic or "", re.I):
            return "SBI PO" if niche_key == "banking_awareness" else "RBI Grade B"
        return None
    return _EXAM_BY_NICHE.get(niche_key or "")


def _ensure_exam_in_title(title: str, topic: str, niche_key: str | None) -> str:
    """Ensure exam name appears in title ONLY for true exam topics.
    For consumer/general topics, leaves the high-CTR search title untouched."""
    title = " ".join((title or "").split())
    exam = _exam_for(topic, niche_key)
    if not exam:
        # Strip any accidental exam prefix from consumer topics
        if niche_key in _NON_EXAM_NICHES:
            title = re.sub(r"^(?:IBPS|SBI|RBI|UPSC|SSC)[\w\s]*[:\|–—-]\s*", "", title, flags=re.I).strip()
        return title[:TITLE_MAX].rstrip()

    m = _EXAM_RE.search(title)
    if m and m.start() <= 25:
        return title[:TITLE_MAX].rstrip()
    if m:
        cleaned = re.sub(r"\b(?:for|in|of)\s+(?:the\s+)?" + re.escape(m.group(1)) + r"(?:\s+exams?)?\b", "",
                         title, count=1, flags=re.I)
        if cleaned == title:
            cleaned = title[:m.start()] + title[m.end():]
        rest = re.sub(r"\s+", " ", cleaned).strip(" -:|–—")
        found = re.sub(r"\s+", " ", m.group(1)).strip()
        title = f"{found}: {rest}"
    else:
        title = f"{exam}: {title}"
    if len(title) > TITLE_MAX:
        cut = title[:TITLE_MAX].rsplit(" ", 1)[0]
        title = cut.rstrip(" :-,")
    return title


def _finalize(script: "Script", topic: str, niche_key: str | None) -> "Script":
    _ensure_cta(script, topic)
    script.title = _ensure_exam_in_title(script.title, topic, niche_key)
    print(f"[final] title={script.title!r} | pinned={script.pinned_comment!r}")
    return script


def seo_optimize_all(
    title: str, description: str, tags: list[str], topic: str, niche_key: str, api_key: str
) -> tuple[str, str, list[str]]:
    """Single Gemini call that optimizes title + description + tags together.

    This REPLACES the old seo_optimize_title() + seo_optimize_description_and_tags()
    pair. Two problems with the old version, both fixed here:

    1. QUOTA: the old functions each called genai directly on only
       _GEMINI_MODELS[0], bypassing the shared fallback/retry/daily-quota-blacklist
       logic in _generate_gemini(). Once the free-tier daily quota on that one
       model was gone (easy — 20 req/day, and every video was already burning
       2-4 calls before this even ran), every SEO call for the rest of the day
       silently failed and the video shipped with its raw, non-optimized title
       and description. This is "where the SEO went."
    2. COST: it was two separate Gemini calls per video. Merging them into one
       halves the SEO budget, so the daily quota stretches over roughly twice
       as many videos before SEO starts falling back to unoptimized text.

    Now routed through _generate_gemini(prompt, api_key) with no model_name,
    so it gets the same model-fallback, 429 retry-with-backoff, and
    daily-quota-blacklist behavior as script generation.
    """
    # Lane-locked channel: the niche pool is exact for the bank-exam niches.
    # Subject-area is only the fallback for unknown niche keys.
    base_tags = _SEO_HASHTAGS_BY_NICHE.get(niche_key) or _SEO_HASHTAGS_BY_SUBJECT_AREA.get(
        classify_subject_area(topic), ["#shorts", "#learneveryday"]
    )
    prompt = f"""You are a YouTube SEO specialist for Indian educational Shorts. You have studied which
titles, descriptions and tags rank highest and get clicked the most for Indian audiences.

TOPIC: {topic}
NICHE: {niche_key}
CURRENT TITLE: {title}
CURRENT DESCRIPTION: {description}
CURRENT TAGS: {tags}

SEO RULES (Search + Clickability):
TITLE:
- If this is an EXAM topic (IBPS, SBI, RBI, GATE, UPSC): Put the EXAM NAME and main concept in the title, e.g. "IBPS SO IT: BCNF vs 3NF" or "BCNF vs 3NF in DBMS | IBPS SO IT".
- If this is a CONSUMER / GENERAL topic (money, tech hacks, psychology, science): DO NOT add exam names like IBPS/SBI! Write a high-CTR, high-intent title, e.g.:
  * Search-focused: "3 Hidden Bank Charges Draining Your Savings Every Month"
  * Curiosity-focused: "Your Bank May Be Quietly Taking This Money Every Month"
  * Direct: "3 Bank Charges That Quietly Drain Your Savings"
- Under 85 characters, accurate, clear, no ALL CAPS, max 1 emoji if natural.
- The title MUST keep the main keywords of the TOPIC. Never change the subject.

DESCRIPTION:
- Line 1: repeat the exam name + concept keywords naturally (what the viewer will learn, for which exam).
- Line 2: one sentence on how it is asked in the exam. Line 3: a question asking viewers to comment their answer or exam date. Line 4: "Follow ExamCrackerAI for daily bank exam revision."
- No keyword stuffing, no made-up facts, no dates/cutoffs.
- End with exactly these hashtags: {' '.join(base_tags)}

TAGS:
- 12-15 tags, lowercase, no '#'. Include the exam names (e.g. ibps so it, sbi po, rbi grade b), the exact concept,
  2-3 long-tail search phrases (e.g. "osi model 7 layers ibps so it"), and "bank exam preparation".

LANGUAGE STYLE (applies to title + description):
- Simple, everyday Indian English — words a 10th-standard student would immediately understand
- No jargon, no complex/uncommon vocabulary, short clear sentences

Return EXACTLY this JSON (no markdown, no commentary):
{{"title": "...", "description": "...", "tags": ["tag1", "tag2", ...]}}"""

    try:
        router = GeminiRouter(api_key=api_key)
        raw = router.generate(prompt, call_type=CallType.SEO)
        raw = re.sub(r"```(?:json)?|```", "", raw).strip()
        data = json.loads(raw)
        new_title = str(data.get("title", title)).strip().strip('"').strip("'")
        new_desc = str(data.get("description", description)).strip()
        new_tags = [str(t).strip().lower().lstrip("#") for t in data.get("tags", tags) if str(t).strip()]
        if not (5 < len(new_title) <= 100):
            new_title = title
        # If the rewrite lost every topic keyword, keep the original title.
        _tk = {t for t in re.findall(r"[a-z0-9]{3,}", topic.lower()) if t not in _TOPIC_STOP}
        _nt = set(re.findall(r"[a-z0-9]{3,}", new_title.lower()))
        if _tk and not (_tk & _nt):
            print(f"[seo] rewritten title dropped all topic keywords — keeping original: {title!r}")
            new_title = title
        if not new_desc:
            new_desc = description
        if not new_tags:
            new_tags = tags
        print(f"[seo] optimized in one call — title={new_title!r}")
        return new_title, new_desc, new_tags
    except Exception as exc:
        print(f"[!] SEO optimization failed (non-fatal, shipping raw title/description/tags): {exc}")
        return title, description, tags


_TOPIC_STOP = {
    "with", "that", "this", "what", "from", "your", "exam", "exams", "bank", "banks", "asked", "every", "trick",
    "easy", "simple", "simply", "explained", "difference", "between", "memory", "know", "need", "for", "and",
    "the", "are", "you", "how", "why", "into", "does", "did", "aspirants", "fastest", "method", "common",
    "solve", "under", "minutes", "minute", "that", "there", "their", "which", "ibps", "sbi",
}


def _topic_issue(topic: str, script: "Script") -> str | None:
    """Reject scripts that drifted off the requested topic."""
    tokens = {t for t in re.findall(r"[a-z0-9]{3,}", topic.lower()) if t not in _TOPIC_STOP}
    if not tokens:
        return None
    body = " ".join([script.title, script.hook] + [s.narration for s in script.scenes]).lower()
    body_tokens = set(re.findall(r"[a-z0-9]{3,}", body))
    hits = sum(1 for t in tokens if t in body_tokens or any(b.startswith(t[:5]) for b in body_tokens if len(t) >= 5))
    if hits / len(tokens) < 0.34:
        return f"script drifted off-topic (matched {hits}/{len(tokens)} topic keywords for {topic!r}); stay strictly on the topic"
    return None


def fact_check_script(
    script: "Script",
    topic: str,
    api_key: str,
    drafter_model: str = "gemini-3.5-flash-lite",
) -> list[str]:
    """Cross-model factual accuracy check.

    gemini-3.5-flash-lite drafts; gemini-3.1-flash-lite fact-checks (exclude_model).
    Two different model weights rarely hallucinate the same thing.
    Non-fatal: if the call fails the pipeline logs a warning and continues.
    """
    narration_dump = "\n".join(
        f"Scene {s.index}: {s.narration}" for s in script.scenes
    )
    prompt = f"""You are a FACTUAL ACCURACY checker for Indian educational content.
Your ONLY job is to catch hard factual errors — NOT style, tone, or pedagogy.

TOPIC: {topic}
TITLE: {script.title}

SCRIPT NARRATION:
{narration_dump}

Check ONLY these things (nothing else):
1. FACTUAL ERRORS: Any statement that is objectively false (e.g. wrong definition of 2NF,
   wrong exam name, invented RBI policy, wrong SQL syntax).
2. INVENTED STATISTICS: Made-up percentages, dates, or numbers with no factual basis.
3. HINDI/DEVANAGARI: Any non-English characters that slipped through.
4. FAKE EXAM QUESTIONS: A question that references a table/diagram that isn't shown
   AND couldn't possibly work without it (not just a CTA or engagement question).

DO NOT flag:
- Hook questions (Scene 0 openers like "Did you know..." or "Can you answer this?")
- Comment CTAs (Scene 4 "Comment below", "Type A/B/C" style endings)
- Simple explanations or analogies, even if imprecise
- Teaching style, pacing, or tone

If everything is factually accurate, return: {{"issues": []}}
If there are FACTUAL problems only, return: {{"issues": ["factual issue 1", "factual issue 2"]}}

Respond ONLY with that JSON. No markdown, no commentary."""

    try:
        router = GeminiRouter(api_key=api_key)
        # Cross-model: exclude the drafter so the checker is a DIFFERENT model.
        raw = router.generate(
            prompt,
            call_type=CallType.FACT_CHECK,
            exclude_model=drafter_model,
            use_schema=False,
        )
        raw = re.sub(r"```(?:json)?|```", "", raw).strip()
        data = json.loads(raw)
        raw_issues = [str(i).strip() for i in data.get("issues", []) if str(i).strip()]
        STYLE_KEYWORDS = ("filler", "engagement", "bait", "hook", "cta", "comment", "vague", "style", "tone", "pedagogy", "pacing")
        issues = []
        for issue in raw_issues:
            if any(k in issue.lower() for k in STYLE_KEYWORDS):
                print(f"[fact-check] Ignoring non-factual/stylistic comment: {issue}")
                continue
            issues.append(issue)
        if issues:
            print(f"[fact-check] {len(issues)} hard factual issue(s) found: {'; '.join(issues)}")
        else:
            print("[fact-check] PASS — no factual issues detected (cross-model)")
        return issues
    except Exception as exc:
        print(f"[fact-check] WARNING: fact-check call failed (non-fatal, continuing): {exc}")
        return []


def polish_script(script: "Script", topic: str, api_key: str) -> "Script":
    """Third-pass polish: hook strength + pacing review.

    Uses CallType.POLISH (thinking=medium, cross-model from drafter).
    Returns the original script unchanged if the call fails (non-fatal).
    """
    narration_dump = "\n".join(
        f"Scene {s.index}: {s.narration}" for s in script.scenes
    )
    prompt = f"""You are a YouTube Shorts editor reviewing an engaging Indian educational video script (under 60 seconds).

TOPIC: {topic}
HOOK (scene 0): {script.scenes[0].narration if script.scenes else ''}

FULL NARRATION:
{narration_dump}

Evaluate ONLY these two things:
1. HOOK: Does the very first line open with a genuine question or a surprising fact
   that makes someone stop scrolling within 3 seconds? If not, rewrite scene 0's
   narration and tts_text to do that — keep the same topic and word count.
2. PACING: Are there any scenes that are clearly too similar in length to each other
   (all 2-3 sentences)? If yes, suggest ONE line that can be cut to create contrast.

Return EXACTLY this JSON and nothing else:
{{
  "hook_ok": true_or_false,
  "hook_fix": "rewritten scene 0 narration, or empty string if hook_ok is true",
  "hook_fix_tts": "same line optimized for TTS, or empty string",
  "pacing_cut": "exact narration sentence to cut (verbatim), or empty string if pacing is fine"
}}"""

    try:
        router = GeminiRouter(api_key=api_key)
        raw = router.generate(
            prompt,
            call_type=CallType.POLISH,
            exclude_model="gemini-3.5-flash-lite",  # cross-model polish
            use_schema=False,
        )
        raw = re.sub(r"```(?:json)?|```", "", raw).strip()
        data = json.loads(raw)

        # Apply hook fix if the model flagged it
        hook_fix = str(data.get("hook_fix") or "").strip()
        hook_fix_tts = str(data.get("hook_fix_tts") or "").strip()
        if hook_fix and script.scenes:
            print(f"[polish] hook rewritten: {hook_fix!r}")
            script.scenes[0].narration = hook_fix
            script.scenes[0].tts_text = hook_fix_tts or hook_fix

        # Apply pacing cut if suggested
        pacing_cut = str(data.get("pacing_cut") or "").strip()
        if pacing_cut:
            for s in script.scenes:
                if pacing_cut in s.narration:
                    candidate = s.narration.replace(pacing_cut, "").strip()
                    # Never cut if it would leave the scene empty or under 5 words
                    if len(candidate.split()) >= 5:
                        s.narration = candidate
                        s.tts_text = (s.tts_text or "").replace(pacing_cut, "").strip()
                        print(f"[polish] pacing cut applied in scene {s.index}: removed {pacing_cut!r}")
                    else:
                        print(f"[polish] pacing cut skipped in scene {s.index}: cut would empty or over-shorten scene")
                    break

        print("[polish] DONE")
        return script
    except Exception as exc:
        print(f"[polish] WARNING: polish pass failed (non-fatal, using original): {exc}")
        return script


# The drafter model is constant — fact-check and polish always exclude it
# so the checker is guaranteed to be a DIFFERENT Flash-Lite weight.
_DRAFTER_MODEL = "gemini-3.5-flash-lite"



def generate_script(topic: str, niche_cfg: dict, language: str, settings, niche_key: str | None = None) -> Script:
    """Three-pass generation: draft -> fact-check -> polish.

    Pass 1 (SCRIPT_GEN):   gemini-3.5-flash-lite, thinking=high, schema-constrained.
    Pass 2 (FACT_CHECK):   gemini-3.1-flash-lite (cross-model), thinking=high.
                           Issues -> repair pass; still fails -> ScriptRejected.
    Pass 3 (POLISH):       gemini-3.1-flash-lite, thinking=medium — hook + pacing.
    SEO:                   gemini-3.5-flash-lite, thinking=low — title/desc/tags.

    ~4-6 Gemini calls per video.  At 500 RPD per Flash-Lite model that is ~80
    videos per day before the tier-3 Gemma fallback kicks in.
    """
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is not set. This pipeline is Google-only.")

    # One router instance per video — shares the persisted quota state so every
    # call (draft, fact-check, polish, SEO, repair) counts against the same day's
    # budget and no model gets double-counted.
    router = GeminiRouter(api_key=settings.gemini_api_key)

    hook_style = _pick_hook_style(topic)
    print(f"[pipeline] hook style for this topic: {hook_style}")
    prompt = _build_prompt(topic, niche_cfg, language, hook_style=hook_style)

    # ── Pass 1: draft (schema-constrained, high thinking) ────────────────────
    print("[pipeline] Pass 1 — draft (schema-constrained, thinking=high)")
    try:
        raw = router.generate(prompt, call_type=CallType.SCRIPT_GEN, use_schema=True)
    except Exception as e:
        raise RuntimeError(f"All Gemini models failed for script generation: {e}") from e

    # ── Parse JSON -----------------------------------------------------------
    # With response_schema active the model MUST return valid JSON, so this
    # branch should almost never fire; kept as a safety net.
    try:
        parsed = _parse_json(raw)
    except Exception as parse_exc:
        print(f"[!] Script JSON invalid: {parse_exc}")
        try:
            print("[pipeline] JSON repair via router (Flash-Lite preferred)")
            repaired_raw = router.generate(
                "Convert the following malformed output into ONLY the exact JSON schema requested. "
                "Do not add markdown or explanations.\n\n" + raw[:12000],
                call_type=CallType.JSON_REPAIR,
                use_schema=False,
            )
            parsed = _parse_json(repaired_raw)
            print("[qa] JSON repair succeeded")
        except Exception as repair_exc:
            raise RuntimeError(f"Gemini returned invalid JSON and repair failed: {repair_exc}") from parse_exc

    # ── QA + topic drift + length + known-error guard ────────────────────────
    script = _to_script(parsed)
    qa = _qa_all(script, topic, language)

    # ── Pass 2: cross-model fact-check (BLOCKING) ────────────────────────────
    print("[pipeline] Pass 2 — cross-model fact-check (thinking=high)")
    if qa.ok:
        fc_issues = fact_check_script(
            script, topic, settings.gemini_api_key, drafter_model=_DRAFTER_MODEL
        )
        if fc_issues:
            qa.issues = list(qa.issues) + [f"FACT: {i}" for i in fc_issues]
            qa.ok = False

    if qa.ok:
        # ── Pass 3: polish (hook + pacing) ───────────────────────────────────
        print("[pipeline] Pass 3 — polish (hook + pacing, thinking=medium)")
        script = polish_script(script, topic, settings.gemini_api_key)
        word_count = sum(len(s.narration.split()) for s in script.scenes)
        print(f"[qa] script passed all 3 passes: scenes={len(script.scenes)} words={word_count}")
        return _seo_and_finalize(script, topic, niche_key, settings)

    # ── Repair pass (fixes length / facts / drift / QA failures) ─────────────
    print("[qa] first draft needs repair: " + "; ".join(qa.issues))
    repair_prompt = _build_prompt(topic, niche_cfg, language, "; ".join(qa.issues), hook_style=hook_style)
    try:
        print("[pipeline] Script repair via router (schema-constrained)")
        raw2 = router.generate(repair_prompt, call_type=CallType.SCRIPT_GEN, use_schema=True)
        repaired = _to_script(_parse_json(raw2))
        qa2 = _qa_all(repaired, topic, language)
        if qa2.ok:
            fc2 = fact_check_script(
                repaired, topic, settings.gemini_api_key, drafter_model=_DRAFTER_MODEL
            )
            if fc2:
                qa2.issues = list(qa2.issues) + [f"FACT: {i}" for i in fc2]
                qa2.ok = False
        if not qa2.ok:
            raise RuntimeError("; ".join(qa2.issues))
        # Polish the repaired script too
        repaired = polish_script(repaired, topic, settings.gemini_api_key)
        print(f"[qa] repaired script passed: scenes={len(repaired.scenes)}")
        return _seo_and_finalize(repaired, topic, niche_key, settings)
    except Exception as exc:
        # Nothing unverified is ever published: caller must skip this topic.
        raise ScriptRejected(f"Script rejected after one repair attempt (not publishing): {exc}") from exc


def _qa_all(script: Script, topic: str, language: str):
    qa = validate_script(script, language)
    extra: list[str] = []
    for check in (_topic_issue(topic, script), _length_issue(script)):
        if check:
            extra.append(check)
    extra += [f"FACT: {m}" for m in _known_fact_issues(script)]
    if extra:
        qa.issues = list(qa.issues) + extra
        qa.ok = False
    return qa


def _seo_and_finalize(script: Script, topic: str, niche_key: str | None, settings) -> Script:
    cluster = get_cluster_for_topic(topic)
    if cluster:
        mode = pick_title_mode(topic, cluster)
        problem_hook = extract_problem_hook(topic) if mode.value == "problem_first" else ""
        script.title = generate_seo_title(cluster, mode, problem_hook)
        script.description = generate_v3_description(cluster)
        script.tags = generate_v3_tags(cluster)
        print(f"[seo_v3] cluster matched: {cluster.primary_query!r}, mode={mode.value}")

    gemini_title, gemini_desc, gemini_tags = seo_optimize_all(
        script.title, script.description, script.tags, topic, niche_key or "", settings.gemini_api_key
    )
    if cluster:
        from .seo.keyword_guard import _contains_query
        if _contains_query(gemini_title, cluster.primary_query):
            script.title = gemini_title
        if _contains_query(gemini_desc[:200], cluster.primary_query):
            script.description = gemini_desc
        if gemini_tags and len(gemini_tags) <= 8:
            script.tags = gemini_tags
    else:
        script.title, script.description, script.tags = gemini_title, gemini_desc, gemini_tags

    script.description = _ensure_hashtags(script.description, topic, niche_key)

    if cluster:
        narration_all = " ".join(s.narration for s in script.scenes)
        screen_texts = [s.on_screen_text for s in script.scenes]
        guard = validate_keyword_density(
            cluster.primary_query,
            script.title,
            script.description,
            narration_all,
            screen_texts,
        )
        if not guard.ok:
            print(f"[seo_v3] keyword guard missing: {guard.missing_surfaces}")
            if "narration" in guard.missing_surfaces:
                script.scenes[0].narration = auto_repair_narration(
                    script.scenes[0].narration, cluster.primary_query
                )
                script.scenes[0].tts_text = auto_repair_narration(
                    script.scenes[0].tts_text, cluster.primary_query
                )
            if "on_screen_text" in guard.missing_surfaces:
                repaired = auto_repair_screen_text(screen_texts, cluster.primary_query)
                for i, text in enumerate(repaired):
                    script.scenes[i].on_screen_text = text
        else:
            print("[seo_v3] keyword guard PASS")

        narration_all = " ".join(s.narration for s in script.scenes)
        screen_texts = [s.on_screen_text for s in script.scenes]
        seo_s = calculate_seo_score(
            cluster, script.title, script.description, narration_all, screen_texts, script.tags
        )
        ret_s = calculate_retention_score(script.scenes)
        pub_s = calculate_final_publish_score(seo_s.total, ret_s.total)
        print(f"[seo_score] SEO={seo_s.total}/100 | Retention={ret_s.total}/100 | Final={pub_s.final}/100")
        script.seo_metadata = {
            "primary_query": cluster.primary_query,
            "seo_score": seo_s.total,
            "retention_score": ret_s.total,
            "final_score": pub_s.final,
            "publish_ready": pub_s.publish_ready,
        }

    bad = _known_fact_issues(script)
    if bad:
        raise ScriptRejected("SEO rewrite introduced factual error(s): " + "; ".join(bad))
    return _finalize(script, topic, niche_key)
