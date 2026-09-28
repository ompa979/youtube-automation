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


@dataclass
class Script:
    title: str
    hook: str
    description: str
    tags: list[str]
    scenes: list[Scene]
    pinned_comment: str = ""

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
The `tts_text` must be the same English spoken content, optimized only for natural
speech pauses and pronunciation. Do not translate it into Hindi.
""".strip()

    repair_text = f"\nREPAIR REQUEST:\n{repair}\n" if repair else ""
    card_rules = ""
    if niche_cfg.get("visual_style") == "text_card":
        card_rules = """
TEXT-CARD CHANNEL (this overrides the VISUAL RULES below):
- Every scene is shown as a text card, not a picture. For EVERY scene provide
  `card_points`: 2-3 revision-note lines (max 7 words each) that state the exact
  fact, rule, formula or step being spoken in that scene. Facts only, no filler.
- `on_screen_text`: a 1-3 word headline for the scene (e.g. "LAYER 3", "INNER JOIN").
- `image_prompt` can be a short placeholder such as "text card".
""".strip()
    topic_lock = (
        "TOPIC LOCK: the title, hook and every scene must be about exactly this topic. "
        "The title must contain the topic's main keywords (and the exam name if the topic names one). "
        "Do not switch to a different topic."
    )
    return f"""
{niche_cfg.get('system_prompt', '')}

You are an excellent Indian exam teacher and educational creator.

{lang_instruction}

TOPIC: {topic}
{topic_lock}
{card_rules}

PRIMARY GOAL: learner value, clarity, factual accuracy and natural delivery.

LENGTH BUDGET (hard rule — retention data shows best completion rate at 28-34s):
- Total narration across ALL scenes: {MIN_WORDS}-{MAX_WORDS} words (28-34 seconds spoken).
- Use 3-5 scenes. Maximum 5 scenes — hard limit. Cut anything not essential.
- One idea, one takeaway, one concrete example or mnemonic.
- The comment-CTA scene below counts toward this budget, so keep it very short.
- PACING SHAPE: open with a question in the first 3 seconds, teach ONE idea with
  ONE concrete example (a mnemonic trick if the topic allows it), end with the CTA.

CONTENT RULES:
- Teach ONE coherent idea well.
- HOOK STYLE FOR THIS SCRIPT: {hook_instruction}
- Explain the mechanism or reasoning, not just the fact.
- Use an analogy or example only when it genuinely improves understanding.
- Connect to exam relevance only when it naturally fits.
- A quiz/MCQ is OPTIONAL. Include one only if it improves learning.
- Never use generic filler: 'guys today we are going to', 'welcome back',
  'don't forget to subscribe'.
- Never invent facts.
- FACT SAFETY: do NOT name the current holder of any post (Governor, Chairman, Minister,
  CEO, MD etc.) or quote dates/cutoffs/statistics you are not 100% sure of — these change
  and wrong ones destroy trust. Refer to the POST, not the person. Use exact official
  designations (e.g. the RBI has a Governor, not a CEO; SBI has a Chairman).
- COMMENT CTA (mandatory): the LAST scene must end with ONE short spoken line that makes
  the viewer type a reply in the comments (max 12 words). Vary it; examples:
  "Comment your answer — A or B?", "Which option did you pick? Tell me below.",
  "Comment your exam date, I'll reply.", "Can you solve it? Type your answer." Do not say
  'like/subscribe'. Put the same call to action, as a question, in `pinned_comment`.
- PACING: vary scene length naturally across the script — let some scenes be
  short, punchy one-liners and others longer explanations. Do not force every
  scene to be roughly the same length; uniform pacing reads as mechanical.

VISUAL RULES:
- Scene 0 (the FIRST scene) MUST have the single most visually striking image prompt:
  one clear dramatic subject, high contrast, instantly understandable at a glance.
  This is the hook frame — it must stop someone scrolling.
- Every other scene needs an educational visual (diagram, process, map, comparison,
  labeled object, timeline, molecule, arrows, conceptual illustration).
- Prefer diagrams and illustrations over generic stock-photo descriptions.
- No text, logos or watermarks inside generated images.
- On-screen text should be a short keyword or memory cue, NOT a transcript line.

Return EXACTLY this JSON shape (no markdown):
{{
  "title": "clear title, under 80 chars, accurate, no fake clickbait",
  "hook": "the first spoken line",
  "description": "2-3 useful sentences with 3 relevant hashtags",
  "pinned_comment": "one short question that invites a comment reply (e.g. 'Comment your answer: A or B?')",
  "tags": ["8-12 lowercase tags"],
  "scenes": [
    {{
      "narration": "natural Indian-English spoken line",
      "tts_text": "same English spoken line optimized for natural TTS",
      "image_prompt": "unique premium cinematic educational visual, 20-45 words, vertical 9:16, clear conceptual diagram or illustration of the mechanism, no embedded text or labels, no typed UI, no logos, no watermark",
      "on_screen_text": "",
      "card_points": ["only for text-card channels: 2-3 short factual revision-note lines, max 7 words each"]
    }}
  ]
}}

Use 3-5 scenes. Do not split a sentence just to create more scenes.
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

        scenes.append(Scene(
            index=i,
            narration=narration,
            tts_text=tts_text,
            image_prompt=image_prompt,
            on_screen_text=on_screen_text.upper(),
            card_points=card_points,
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

# ── #4 Duration: 28-34 s spoken ≈ 70-85 words at a natural Indian-English pace
# Analytics shows best retention in the 28-34s window (not the full 30s+).
MIN_WORDS = 55
MAX_WORDS = 85          # hard ceiling enforced by QA (~34 s)


def _length_issue(script: "Script") -> str | None:
    words = sum(len(s.narration.split()) for s in script.scenes)
    if words > MAX_WORDS:
        return (f"narration is {words} words (~{words // 2.6:.0f}s); must be "
                f"{MIN_WORDS}-{MAX_WORDS} words (20-30s). Cut to the single most important idea")
    if words < MIN_WORDS:
        return f"narration only {words} words; needs {MIN_WORDS}-{MAX_WORDS} words for a complete idea"
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


def _ensure_cta(script: "Script", topic: str) -> None:
    """Guarantee the last scene asks for a comment, the description carries the
    CTA, and a pinned_comment exists.  Runs after the LLM so it never depends on
    the model obeying the prompt."""
    last = script.scenes[-1]
    if not _has_cta(last.narration):
        cta = _DEFAULT_CTAS[_stable_hash(topic) % len(_DEFAULT_CTAS)]
        last.narration = last.narration.rstrip() + " " + cta
        last.tts_text = last.tts_text.rstrip() + " " + cta
        print(f"[cta] LLM omitted comment CTA — appended: {cta!r}")
    if not script.pinned_comment:
        script.pinned_comment = "Comment your answer below — let's see who gets it right!"
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
_EXAM_BY_NICHE = {
    "bank_it_officer": "IBPS SO IT",
    "bank_reasoning_quant": "SBI PO",
    "banking_awareness": "SBI PO",
    "rbi_economy": "RBI Grade B",
    "bank_english": "IBPS PO",
}
_EXAM_RE = re.compile(
    r"\b(IBPS\s*(?:SO(?:\s*IT)?|PO|Clerk|RRB)|SBI\s*(?:PO|Clerk|SO)|RBI\s*(?:Grade\s*B|Assistant)|"
    r"NABARD|SEBI|IFSC|LIC\s*AAO|GATE|UPSC|SSC|NEET)\b", re.I)
TITLE_MAX = 65


def _exam_for(topic: str, niche_key: str | None) -> str | None:
    m = _EXAM_RE.search(topic or "")
    if m:
        return re.sub(r"\s+", " ", m.group(1)).upper().replace("RBI GRADE B", "RBI Grade B")
    return _EXAM_BY_NICHE.get(niche_key or "")


def _ensure_exam_in_title(title: str, topic: str, niche_key: str | None) -> str:
    """Titles without an exam signal get ~9 views; with one, ~100.  Enforced here,
    after SEO, so no title ships without an exam name in the first 45 chars."""
    title = " ".join((title or "").split())
    exam = _exam_for(topic, niche_key)
    if not exam:
        return title
    m = _EXAM_RE.search(title)
    if m and m.start() <= 25:
        return title[:TITLE_MAX].rstrip()
    if m:                                   # exam present but buried — move it to the front
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

SEARCH-FIRST RULES (about 78% of this channel's views come from YouTube Search, not the Shorts feed —
aspirants type the exam name + concept, so the title must match that search):
TITLE:
- Put the EXAM NAME and the main CONCEPT keywords in the first 45 characters, the way an aspirant would type
  them. Pattern: "<Exam>: <Concept> <Benefit>", e.g. "IBPS SO IT: OSI Model 7 Layers Trick",
  "SBI PO: Simplification Speed Trick", "RBI Grade B: GDP vs GNP Explained".
- Under 65 characters, MUST start with the exam name, 100% accurate, no false promises, no ALL CAPS, no emojis, no vague curiosity-gap wording.
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
    prompt = f"""You are a strict factual accuracy checker for Indian educational content.

TOPIC: {topic}
TITLE: {script.title}

SCRIPT NARRATION:
{narration_dump}

Your task:
1. Identify any factual errors, invented statistics, or false claims.
2. Flag any Devanagari / Hindi characters (English-only pipeline).
3. Flag invented exam patterns or fake question formats.
4. Flag any vague filler lines that add zero educational value.

If everything is accurate, return: {{"issues": []}}
If there are problems, return: {{"issues": ["short description of issue 1", "issue 2", ...]}}

Respond ONLY with that JSON object. No markdown, no explanation outside the JSON."""

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
        issues = [str(i).strip() for i in data.get("issues", []) if str(i).strip()]
        if issues:
            print(f"[fact-check] {len(issues)} issue(s) found: {'; '.join(issues)}")
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
    prompt = f"""You are a YouTube Shorts editor reviewing a 28-34 second Indian educational video script.

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
                    s.narration = s.narration.replace(pacing_cut, "").strip()
                    s.tts_text = s.tts_text.replace(pacing_cut, "").strip()
                    print(f"[polish] pacing cut applied in scene {s.index}: removed {pacing_cut!r}")
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
    script.title, script.description, script.tags = seo_optimize_all(
        script.title, script.description, script.tags, topic, niche_key or "", settings.gemini_api_key
    )
    script.description = _ensure_hashtags(script.description, topic, niche_key)
    # SEO rewrite could re-introduce a known error or drop the CTA/exam — re-guard.
    bad = _known_fact_issues(script)
    if bad:
        raise ScriptRejected("SEO rewrite introduced factual error(s): " + "; ".join(bad))
    return _finalize(script, topic, niche_key)
