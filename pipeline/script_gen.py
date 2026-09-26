"""Natural Indian-English educational script generation.

Gemini 2.5 Flash is the PRIMARY model — it's Google's best free-tier model
with superior reasoning and long context. Gemini 1.5 Flash is the fallback.
OpenRouter is intentionally removed so you never silently downgrade to a
weak model.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, asdict

import google.generativeai as genai

from .quality import validate_script

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


def _build_prompt(topic: str, niche_cfg: dict, language: str, repair: str | None = None) -> str:
    lang_instruction = """
Write the viewer-facing narration in clear, natural conversational Indian English.
Use an Indian English speaking style: simple phrasing, natural rhythm, familiar
Indian examples where useful, but do NOT use Hinglish, Roman Hindi, Devanagari,
or forced Indian slang. Keep technical terms in standard English.
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
Do NOT optimize for a fixed duration. Do NOT shorten an explanation merely to
fit a target number of seconds. Do NOT add filler to make it longer. Let the
concept determine how much narration is needed.

CONTENT RULES:
- Teach ONE coherent idea well.
- Start naturally with a question, surprising observation, problem, or useful exam connection. Do not use the same hook pattern repeatedly.
- Explain the mechanism or reasoning, not just the fact.
- Use an analogy or example only when it genuinely improves understanding.
- Introduce difficult technical terms and immediately make them understandable.
- Connect to exam relevance only when it naturally fits the topic.
- A quiz/MCQ is OPTIONAL. Include one only if it improves learning.
- A CTA is OPTIONAL and must never interrupt the explanation.
- Never use generic filler such as 'guys, today we are going to', 'welcome back', or 'don't forget to subscribe'.
- Never invent facts. If a topic is uncertain, explain only what is well-established.

VISUAL RULES:
- Every scene needs an educational visual, not decorative stock imagery.
- The image prompt must describe what should be shown to help the learner understand the narration.
- Prefer diagrams, processes, maps, comparisons, labeled objects, timelines, molecules, arrows, or simple conceptual illustrations when appropriate.
- No text, logos or watermarks inside generated images.
- On-screen text should be a short keyword or memory cue, not a transcript.

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
      "image_prompt": "unique premium cinematic educational visual, 20-45 words, vertical 9:16, clear conceptual diagram or illustration of the mechanism, no embedded text or labels (on-screen captions are added separately), no typed UI, no logos, no watermark",
      "on_screen_text": ""
    }}
  ]
}}

Use as many scenes as the explanation naturally needs, normally 3-8.
Do not split a sentence just to create more scenes.
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
    for candidate in candidates:
        if candidate not in seen:
            seen.add(candidate)
            unique.append(candidate)
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
                repaired = _remove_trailing_commas(candidate)
                value = json.loads(repaired)
                if isinstance(value, dict):
                    return value
            except json.JSONDecodeError:
                pass

    raise ValueError(
        "Gemini returned invalid JSON: " + " | ".join(errors[:4])
        + f"\nRAW:\n{(raw or '')[:1200]}"
    )


def _generate_gemini(prompt: str, api_key: str, model_name: str | None = None) -> str:
    """Call Gemini. model_name defaults to gemini-2.5-flash (best free tier)."""
    genai.configure(api_key=api_key)
    # gemini-2.5-flash is the best free-quota model as of mid-2025.
    # It has superior reasoning vs 1.5-flash and a 1M token context window.
    # Fallback: gemini-1.5-flash (older but very reliable).
    model_to_use = model_name or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    model = genai.GenerativeModel(model_to_use, generation_config={
        "temperature": 0.75,
        "response_mime_type": "application/json",
    })
    resp = model.generate_content(prompt)
    text = getattr(resp, "text", None)
    if not text:
        raise RuntimeError(f"Gemini ({model_to_use}) returned an empty response")
    return text


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

        narration = _first_text(
            raw, "narration", "voiceover", "voice_over", "spoken_text",
            "speech", "dialogue", "text", "script",
        )
        tts_text = _first_text(
            raw, "tts_text", "tts", "voice_text", "voiceover", "voice_over",
            "narration", "spoken_text", "speech", "dialogue", "text", "script",
        )

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
            raise ValueError(f"Generated scene {i + 1} contains Devanagari/Hindi text; English-only output required")

        image_prompt = _first_text(
            raw, "image_prompt", "visual_prompt", "visual", "image", "prompt"
        )
        if not image_prompt:
            image_prompt = (
                "A fresh handwritten study-notes composition that visually explains the narration "
                "with hand-drawn diagrams, arrows, circles and selective handwritten labels."
            )
        on_screen_text = _first_text(
            raw, "on_screen_text", "caption", "keyword", "memory_cue"
        )

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


def generate_script(topic: str, niche_cfg: dict, language: str, settings) -> Script:
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is not set. This pipeline is Google-only.")

    prompt = _build_prompt(topic, niche_cfg, language)

    # PRIMARY: Gemini 2.5 Flash — Google's best free-quota model (as of 2025)
    # FALLBACK: Gemini 1.5 Flash — older but very reliable
    raw: str | None = None
    for model_name in ["gemini-2.5-flash", "gemini-1.5-flash"]:
        try:
            print(f"[pipeline] Script generator: Gemini ({model_name})")
            raw = _generate_gemini(prompt, settings.gemini_api_key, model_name)
            break
        except Exception as e:
            print(f"[!] Gemini {model_name} failed: {e}")

    if raw is None:
        raise RuntimeError("All Gemini models failed for script generation")

    try:
        parsed = _parse_json(raw)
    except Exception as parse_exc:
        print(f"[!] Script JSON invalid: {parse_exc}")
        # Ask Gemini 1.5 flash to repair the JSON (it's very good at this)
        try:
            print("[pipeline] JSON repair: Gemini 1.5 Flash")
            repaired_raw = _generate_gemini(
                "Convert the following malformed output into ONLY the exact JSON schema requested. "
                "Do not add markdown or explanations.\n\n" + raw[:12000],
                settings.gemini_api_key,
                "gemini-1.5-flash",
            )
            parsed = _parse_json(repaired_raw)
            print("[qa] JSON repair succeeded")
        except Exception as repair_exc:
            raise RuntimeError(f"Gemini returned invalid JSON and repair failed: {repair_exc}") from parse_exc

    script = _to_script(parsed)
    qa = validate_script(script, language)
    if qa.ok:
        print(f"[qa] script passed: scenes={len(script.scenes)} words={sum(len(s.narration.split()) for s in script.scenes)}")
        return script

    print("[qa] first script needs repair: " + "; ".join(qa.issues))
    repair_prompt = _build_prompt(topic, niche_cfg, language, "; ".join(qa.issues))
    try:
        print("[pipeline] Script repair: Gemini 2.5 Flash")
        raw2 = _generate_gemini(repair_prompt, settings.gemini_api_key, "gemini-2.5-flash")
        repaired = _to_script(_parse_json(raw2))
        qa2 = validate_script(repaired, language)
        if not qa2.ok:
            raise RuntimeError("; ".join(qa2.issues))
        print(f"[qa] repaired script passed: scenes={len(repaired.scenes)}")
        return repaired
    except Exception as exc:
        raise RuntimeError(f"Generated script failed QA after one repair attempt: {exc}") from exc
