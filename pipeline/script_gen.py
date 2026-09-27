"""Natural Indian-English educational script generation.

Gemini 3.8 Flash is the PRIMARY model.
Gemini 3.5 Flash Lite is the fallback.
All models are Google — no OpenRouter dependency.

Also provides:
  - seo_optimize_title(): second Gemini call to maximize CTR/search rank
  - Hook image rule: scene 0 always forced to a striking single-subject visual
  - Hook STYLE rotation (question / shocking-fact / numbered) per topic, so
    every video doesn't open the same way (anti-monotone optimization #7)
  - A pacing rule asking the model to vary scene length naturally instead of
    uniform-length scenes (anti-monotone optimization #8)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, asdict

import google.generativeai as genai

from .quality import validate_script
from .subject_area import classify_subject_area


# Ordered fallback list used by every Gemini call site in this module.
# gemini-2.0-flash and gemini-2.0-flash-lite are both deprecated (404).
# gemini-3.8-flash is now the primary; gemini-3.5-flash-lite is the fallback.
# Add newer models here when they become available — all call sites pick
# them up automatically without any further changes.
_GEMINI_MODELS: list[str] = [
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite",
]

# Maximum seconds to wait on a 429 retry-delay hint before giving up and
# trying the next model. Keeps CI runs from stalling indefinitely.
# Lowered from 70s -> 25s: with only 2 models in the fallback chain, a single
# stall this long is a meaningful chunk of total build time; 25s still covers
# almost every short RPM-window 429 while failing over to the next model
# much faster when it doesn't.
_MAX_RETRY_WAIT_SECONDS: int = 25

# Models blacklisted for the remainder of this process after returning a
# *daily* quota exhaustion (GenerateRequestsPerDayPerProjectPerModel-FreeTier).
# These are never retried — their daily budget is gone for 24 h and every
# further attempt just burns time.  Short-window RPM 429s (retry_delay ≤
# _MAX_RETRY_WAIT_SECONDS) still get the normal one-retry treatment.
_DAILY_QUOTA_BLACKLIST: set[str] = set()


def _is_daily_quota_error(exc: Exception) -> bool:
    """Return True when the error is a *per-day* quota exhaustion, not an RPM spike."""
    msg = str(exc)
    return "GenerateRequestsPerDayPerProjectPerModel" in msg or (
        "quota" in msg.lower() and "day" in msg.lower()
    )


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


@dataclass
class Scene:
    index: int
    narration: str
    tts_text: str
    image_prompt: str
    on_screen_text: str


@dataclass
class Script:
    title: str
    hook: str
    description: str
    tags: list[str]
    scenes: list[Scene]

    def to_dict(self) -> dict:
        return {
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
    return f"""
{niche_cfg.get('system_prompt', '')}

You are an excellent Indian exam teacher and educational creator.

{lang_instruction}

TOPIC: {topic}

PRIMARY GOAL: learner value, clarity, factual accuracy and natural delivery.
Do NOT optimize for a fixed duration. Let the concept determine narration length.

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
  "tags": ["8-12 lowercase tags"],
  "scenes": [
    {{
      "narration": "natural Indian-English spoken line",
      "tts_text": "same English spoken line optimized for natural TTS",
      "image_prompt": "unique premium cinematic educational visual, 20-45 words, vertical 9:16, clear conceptual diagram or illustration of the mechanism, no embedded text or labels, no typed UI, no logos, no watermark",
      "on_screen_text": ""
    }}
  ]
}}

Use 3-8 scenes. Do not split a sentence just to create more scenes.
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


def _parse_retry_delay(exc: Exception) -> float | None:
    """Return the retry_delay in seconds from a Gemini 429 error, or None."""
    msg = str(exc)
    # The gRPC error body contains `retry_delay { seconds: N }`.
    m = re.search(r"retry_delay\s*\{\s*seconds:\s*(\d+)", msg)
    if m:
        return float(m.group(1))
    # Fall back to a plain "Please retry in N.NNs" hint.
    m = re.search(r"retry in\s+([\d.]+)s", msg, re.I)
    if m:
        return float(m.group(1))
    return None


def _generate_gemini(prompt: str, api_key: str, model_name: str | None = None) -> str:
    """Call Gemini with a single explicit model, or walk _GEMINI_MODELS on failure.

    Passing `model_name` pins to that model (used by call sites that already
    loop externally).  Omitting it lets this function try each entry in
    _GEMINI_MODELS in order so callers don't need to duplicate the fallback
    logic.

    429 quota errors: if the API supplies a retry_delay ≤ _MAX_RETRY_WAIT_SECONDS
    we sleep and retry the *same* model once before moving on.  This handles
    short-window rate limits (RPM) without burning the daily quota of the next
    model unnecessarily.  Delays longer than _MAX_RETRY_WAIT_SECONDS (e.g. a
    daily-quota exhaustion) are treated as a hard failure and the next model
    is tried immediately.
    """
    genai.configure(api_key=api_key)
    candidates = [model_name] if model_name else _GEMINI_MODELS
    last_exc: Exception | None = None

    for model_to_use in candidates:
        # Skip models whose daily free-tier quota is already exhausted.
        if model_to_use in _DAILY_QUOTA_BLACKLIST:
            print(f"[!] Gemini {model_to_use} skipped — daily quota exhausted this run")
            continue

        retry_attempted = False
        while True:
            try:
                model = genai.GenerativeModel(model_to_use, generation_config={
                    "temperature": 0.75,
                    "response_mime_type": "application/json",
                })
                resp = model.generate_content(prompt)
                text = getattr(resp, "text", None)
                if not text:
                    raise RuntimeError(f"Gemini ({model_to_use}) returned an empty response")
                return text
            except Exception as exc:
                is_429 = "429" in str(exc) or "quota" in str(exc).lower()
                if is_429:
                    if _is_daily_quota_error(exc):
                        # Daily budget is gone — blacklist for the rest of the process.
                        _DAILY_QUOTA_BLACKLIST.add(model_to_use)
                        print(f"[!] Gemini {model_to_use} daily quota exhausted — blacklisted for this run")
                        last_exc = exc
                        break  # move to next model immediately
                    if not retry_attempted:
                        delay = _parse_retry_delay(exc)
                        if delay is not None and delay <= _MAX_RETRY_WAIT_SECONDS:
                            print(f"[!] Gemini {model_to_use} rate-limited — retrying in {delay:.0f}s")
                            time.sleep(delay + 1)  # +1s safety buffer
                            retry_attempted = True
                            continue  # retry same model
                print(f"[!] Gemini {model_to_use} failed: {exc}")
                last_exc = exc
                break  # move to next model

    raise RuntimeError(f"All Gemini models failed: {last_exc}") from last_exc


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

        scenes.append(Scene(
            index=i,
            narration=narration,
            tts_text=tts_text,
            image_prompt=image_prompt,
            on_screen_text=on_screen_text.upper(),
        ))

    return Script(
        title=str(data.get("title", "")).strip(),
        hook=str(data.get("hook", "")).strip(),
        description=str(data.get("description", "")).strip(),
        tags=[str(t).lower().lstrip("#") for t in data.get("tags", [])][:15],
        scenes=scenes,
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
    pool = _SEO_HASHTAGS_BY_SUBJECT_AREA.get(
        classify_subject_area(topic),
        HASHTAG_POOL.get(niche_key or "", HASHTAG_POOL["default"]),
    )
    existing_lower = {e.lower() for e in existing}
    to_add = [h for h in pool if h.lower() not in existing_lower][: 3 - len(existing)]
    if not to_add:
        return description
    return description.rstrip() + "\n\n" + " ".join(to_add)


_SEO_HASHTAGS_BY_NICHE = {
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
    base_tags = _SEO_HASHTAGS_BY_SUBJECT_AREA.get(
        classify_subject_area(topic),
        _SEO_HASHTAGS_BY_NICHE.get(niche_key, ["#shorts", "#learneveryday"]),
    )
    prompt = f"""You are a YouTube SEO specialist for Indian educational Shorts. You have studied which
titles, descriptions and tags rank highest and get clicked the most for Indian audiences.

TOPIC: {topic}
NICHE: {niche_key}
CURRENT TITLE: {title}
CURRENT DESCRIPTION: {description}
CURRENT TAGS: {tags}

VIRAL TITLE FORMULA for Indian educational Shorts (use whichever fits the topic best):
- Curiosity gap: "Why [Relatable Thing] Actually [Surprising Explanation]"
- Benefit + secret: "The [One/Real] Reason [Thing] — Most People Don't Know This"
- Pride/identity: "India [Did/Has/Built] [Surprising Fact] — Here's Why"
- You-frame: "Why YOUR [Body/Brain/Phone] Does [Thing] Explained"

TITLE RULES:
- Under 60 characters, 100% accurate, no false promises, no ALL CAPS, no emojis
- Use the most-searched keywords for this topic among Indian viewers
- If the current title already fits these patterns well, keep it unchanged

DESCRIPTION RULES:
- First sentence must contain the most-searched keywords for this topic in India
- 2-3 sentences max, natural language, not keyword stuffing
- Include a light call-to-action: 'Follow for more [topic area] explained simply'
- End with exactly these hashtags: {' '.join(base_tags)}

TAGS RULES:
- 10-15 tags, all lowercase, no '#' symbol
- Mix broad (india, education, shorts) + specific (the exact concept) + long-tail ('why does x happen')

LANGUAGE STYLE (applies to title + description):
- Simple, everyday Indian English — words a 10th-standard student would immediately understand
- No jargon, no complex/uncommon vocabulary, short clear sentences

Return EXACTLY this JSON (no markdown, no commentary):
{{"title": "...", "description": "...", "tags": ["tag1", "tag2", ...]}}"""

    try:
        raw = _generate_gemini(prompt, api_key)
        raw = re.sub(r"```(?:json)?|```", "", raw).strip()
        data = json.loads(raw)
        new_title = str(data.get("title", title)).strip().strip('"').strip("'")
        new_desc = str(data.get("description", description)).strip()
        new_tags = [str(t).strip().lower().lstrip("#") for t in data.get("tags", tags) if str(t).strip()]
        if not (5 < len(new_title) <= 100):
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


def generate_script(topic: str, niche_cfg: dict, language: str, settings, niche_key: str | None = None) -> Script:
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is not set. This pipeline is Google-only.")

    hook_style = _pick_hook_style(topic)
    print(f"[pipeline] hook style for this topic: {hook_style}")
    prompt = _build_prompt(topic, niche_cfg, language, hook_style=hook_style)

    # No model_name → walks _GEMINI_MODELS with the shared fallback/retry/
    # daily-quota-blacklist logic (previously this call site had its own bare
    # loop that didn't retry 429s or respect the blacklist, so it could waste
    # time re-hitting a model already known to be exhausted for the day).
    try:
        raw = _generate_gemini(prompt, settings.gemini_api_key)
    except Exception as e:
        raise RuntimeError(f"All Gemini models failed for script generation: {e}") from e

    try:
        parsed = _parse_json(raw)
    except Exception as parse_exc:
        print(f"[!] Script JSON invalid: {parse_exc}")
        try:
            print(f"[pipeline] JSON repair: trying {_GEMINI_MODELS}")
            repaired_raw = _generate_gemini(
                "Convert the following malformed output into ONLY the exact JSON schema requested. "
                "Do not add markdown or explanations.\n\n" + raw[:12000],
                settings.gemini_api_key,
                # No model_name → _generate_gemini walks _GEMINI_MODELS with fallback
            )
            parsed = _parse_json(repaired_raw)
            print("[qa] JSON repair succeeded")
        except Exception as repair_exc:
            raise RuntimeError(f"Gemini returned invalid JSON and repair failed: {repair_exc}") from parse_exc

    script = _to_script(parsed)
    qa = validate_script(script, language)
    if qa.ok:
        print(f"[qa] script passed: scenes={len(script.scenes)} words={sum(len(s.narration.split()) for s in script.scenes)}")
        # Optimization #3: SEO-optimize title + description + tags in one call
        script.title, script.description, script.tags = seo_optimize_all(
            script.title, script.description, script.tags, topic, niche_key or "", settings.gemini_api_key
        )
        script.description = _ensure_hashtags(script.description, topic, niche_key)
        return script

    print("[qa] first script needs repair: " + "; ".join(qa.issues))
    repair_prompt = _build_prompt(topic, niche_cfg, language, "; ".join(qa.issues), hook_style=hook_style)
    try:
        print(f"[pipeline] Script repair: trying {_GEMINI_MODELS}")
        raw2 = _generate_gemini(repair_prompt, settings.gemini_api_key)
        # No model_name → _generate_gemini walks _GEMINI_MODELS with fallback
        repaired = _to_script(_parse_json(raw2))
        qa2 = validate_script(repaired, language)
        if not qa2.ok:
            raise RuntimeError("; ".join(qa2.issues))
        print(f"[qa] repaired script passed: scenes={len(repaired.scenes)}")
        repaired.title, repaired.description, repaired.tags = seo_optimize_all(
            repaired.title, repaired.description, repaired.tags, topic, niche_key or "", settings.gemini_api_key
        )
        repaired.description = _ensure_hashtags(repaired.description, topic, niche_key)
        return repaired
    except Exception as exc:
        raise RuntimeError(f"Generated script failed QA after one repair attempt: {exc}") from exc
