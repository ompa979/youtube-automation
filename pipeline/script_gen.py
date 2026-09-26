"""Natural Hinglish educational script generation.

OpenRouter is the primary LLM and Gemini is the fallback. Duration is never a
prompt constraint: the amount of explanation required to teach the concept
controls the final runtime.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, asdict

import google.generativeai as genai
import requests

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
    if language == "hinglish":
        lang_instruction = """
Write the viewer-facing narration in natural Indian Hinglish using Roman Hindi
plus English technical terms. It should sound like a knowledgeable Indian
teacher speaking naturally to an aspirant. Use respectful conversational Hindi
(aap/hum) where natural. Do NOT translate every technical term into Hindi.
Do NOT use Devanagari in narration.

Also provide `tts_text`: the same spoken content optimized for a Hindi-capable
voice. For Hindi words, use Devanagari; keep technical terms, acronyms, proper
nouns and common English words in Latin script where that improves pronunciation.
Do not change the meaning between narration and tts_text.
""".strip()
    elif language == "hi":
        lang_instruction = "Write natural spoken Hindi in Devanagari, keeping technical terms in English when useful."
    else:
        lang_instruction = "Write clear, conversational English suitable for an Indian exam learner."

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
      "narration": "Roman Hinglish spoken line for captions",
      "tts_text": "same spoken line optimized for Hindi-capable TTS",
      "image_prompt": "educational visual description, 15-35 words, vertical 9:16, no text, no logos",
      "on_screen_text": "2-8 word keyword or memory cue"
    }}
  ]
}}

Use as many scenes as the explanation naturally needs, normally 3-8.
Do not split a sentence just to create more scenes.
{repair_text}
""".strip()


def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?", "", raw).strip()
    raw = re.sub(r"```$", "", raw).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object found in LLM output:\n{raw[:500]}")
    return json.loads(raw[start:end + 1])


def _generate_gemini(prompt: str, api_key: str) -> str:
    genai.configure(api_key=api_key)
    model_name = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
    model = genai.GenerativeModel(model_name, generation_config={
        "temperature": 0.75,
        "response_mime_type": "application/json",
    })
    resp = model.generate_content(prompt)
    text = getattr(resp, "text", None)
    if not text:
        raise RuntimeError("Gemini returned an empty response")
    return text


def _generate_openrouter(prompt: str, api_key: str) -> str:
    endpoint = os.getenv("OPENROUTER_ENDPOINT", "https://openrouter.ai/api/v1/chat/completions")
    configured = os.getenv("OPENROUTER_MODEL")
    models = [configured] if configured else ["openrouter/free", "openai/gpt-oss-120b:free"]
    last_error: Exception | None = None
    for model_name in models:
        if not model_name:
            continue
        try:
            r = requests.post(
                endpoint,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://examcracker-ai.onrender.com",
                    "X-Title": "ExamCracker YouTube Automation",
                },
                json={
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": "Return only valid JSON. You are an expert Indian educational content creator."},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.75,
                    "response_format": {"type": "json_object"},
                },
                timeout=90,
            )
            if not r.ok:
                raise RuntimeError(f"OpenRouter model {model_name} returned HTTP {r.status_code}: {r.text[:800]}")
            data = r.json()
            content = data["choices"][0]["message"]["content"]
            if not content:
                raise RuntimeError(f"OpenRouter model {model_name} returned empty content")
            return content
        except Exception as exc:
            last_error = exc
    raise RuntimeError(str(last_error) if last_error else "No OpenRouter model configured")


def _to_script(data: dict) -> Script:
    scenes: list[Scene] = []
    for i, raw in enumerate(data.get("scenes", [])):
        narration = str(raw.get("narration", "")).strip()
        scenes.append(Scene(
            index=i,
            narration=narration,
            tts_text=str(raw.get("tts_text") or narration).strip(),
            image_prompt=str(raw.get("image_prompt", "")).strip(),
            on_screen_text=str(raw.get("on_screen_text", "")).strip().upper(),
        ))
    return Script(
        title=str(data.get("title", "")).strip(),
        hook=str(data.get("hook", "")).strip(),
        description=str(data.get("description", "")).strip(),
        tags=[str(t).lower().lstrip("#") for t in data.get("tags", [])][:15],
        scenes=scenes,
    )


def generate_script(topic: str, niche_cfg: dict, language: str, settings) -> Script:
    prompt = _build_prompt(topic, niche_cfg, language)
    raw: str | None = None
    errors: list[str] = []

    if settings.openrouter_api_key:
        print("[pipeline] Script generator: OpenRouter (PRIMARY)")
        try:
            raw = _generate_openrouter(prompt, settings.openrouter_api_key)
        except Exception as e:
            errors.append(f"openrouter: {e}")
            print(f"[!] OpenRouter primary failed: {e}")

    if raw is None and settings.gemini_api_key:
        print("[pipeline] Script generator: Gemini (FALLBACK)")
        try:
            raw = _generate_gemini(prompt, settings.gemini_api_key)
        except Exception as e:
            errors.append(f"gemini: {e}")
            print(f"[!] Gemini fallback failed: {e}")

    if raw is None:
        raise RuntimeError(f"All script generators failed: {errors}")

    script = _to_script(_parse_json(raw))
    qa = validate_script(script, language)
    if qa.ok:
        print(f"[qa] script passed: scenes={len(script.scenes)} words={sum(len(s.narration.split()) for s in script.scenes)}")
        return script

    print("[qa] first script needs repair: " + "; ".join(qa.issues))
    repair_prompt = _build_prompt(topic, niche_cfg, language, "; ".join(qa.issues))
    try:
        if settings.openrouter_api_key:
            print("[pipeline] Script repair: OpenRouter (PRIMARY)")
            raw2 = _generate_openrouter(repair_prompt, settings.openrouter_api_key)
        elif settings.gemini_api_key:
            print("[pipeline] Script repair: Gemini (FALLBACK)")
            raw2 = _generate_gemini(repair_prompt, settings.gemini_api_key)
        else:
            raise RuntimeError("No LLM key available for script repair")
        repaired = _to_script(_parse_json(raw2))
        qa2 = validate_script(repaired, language)
        if not qa2.ok:
            raise RuntimeError("; ".join(qa2.issues))
        print(f"[qa] repaired script passed: scenes={len(repaired.scenes)}")
        return repaired
    except Exception as exc:
        raise RuntimeError(f"Generated script failed QA after one repair attempt: {exc}") from exc
