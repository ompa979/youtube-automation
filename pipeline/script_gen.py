"""Script generation via Gemini 2.5 Flash, with OpenRouter fallback."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict

import google.generativeai as genai
import requests

@dataclass
class Scene:
    index: int
    narration: str
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

def _build_prompt(topic: str, niche_cfg: dict, language: str, target_seconds: int) -> str:
    lang_instruction = {
        "en": "Write in clear, conversational English.",
        "hi": "Write in natural Hindi (Devanagari script). Keep it simple and spoken, not literary.",
        "hinglish": "Write in casual Hinglish — a natural mix of Hindi and English as spoken by urban Indian youth. Use Roman script for the Hindi parts (e.g. 'yaar', 'matlab', 'bilkul').",
    }.get(language, "Write in English.")

    return f"""
{niche_cfg['system_prompt']}

{lang_instruction}

TOPIC: {topic}

Produce a YouTube Short script with EXACTLY this JSON shape (no markdown, no code fences):
{{
  "title": "catchy YouTube title, under 70 chars, no clickbait lies",
  "hook": "the very first spoken line, under 12 words, designed to stop scrolling",
  "description": "2-3 sentence YouTube description ending with 3 relevant hashtags",
  "tags": ["8-12 lowercase tags, no # symbol"],
  "scenes": [
    {{
      "narration": "the spoken line for this scene (1-2 sentences max)",
      "image_prompt": "a detailed visual description for an AI image generator, 15-30 words, cinematic, no text in image, no logos",
      "on_screen_text": "3-6 words in ALL CAPS to burn on screen"
    }}
  ]
}}

RULES:
- Total narration across all scenes must be readable aloud in about {target_seconds} seconds (roughly {int(target_seconds*2.6)} words).
- Use 4 to 6 scenes. First scene = the hook. Last scene = a memorable payoff.
- Every image_prompt must describe a DIFFERENT visual — no repetition.
- No emojis in narration. No stage directions. No "welcome back".
- Output ONLY the JSON object. Nothing before or after.
""".strip()

def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?", "", raw).strip()
    raw = re.sub(r"```$", "", raw).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object found in LLM output:\n{raw[:400]}")
    return json.loads(raw[start:end + 1])

def _generate_gemini(prompt: str, api_key: str) -> str:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        "gemini-2.5-flash",
        generation_config={
            "temperature": 0.9,
            "response_mime_type": "application/json",
        },
    )
    resp = model.generate_content(prompt)
    return resp.text

def _generate_openrouter(prompt: str, api_key: str) -> str:
    r = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": "meta-llama/llama-3.3-70b-instruct:free",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.9,
            "response_format": {"type": "json_object"},
        },
        timeout=90,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]

def generate_script(topic: str, niche_cfg: dict, language: str, settings) -> Script:
    target_seconds = int(niche_cfg.get("video_length_sec", 45))
    prompt = _build_prompt(topic, niche_cfg, language, target_seconds)

    raw: str | None = None
    errors: list[str] = []

    if settings.gemini_api_key:
        try:
            raw = _generate_gemini(prompt, settings.gemini_api_key)
        except Exception as e:
            errors.append(f"gemini: {e}")

    if raw is None and settings.openrouter_api_key:
        try:
            raw = _generate_openrouter(prompt, settings.openrouter_api_key)
        except Exception as e:
            errors.append(f"openrouter: {e}")

    if raw is None:
        raise RuntimeError(f"All script generators failed: {errors}")

    data = _parse_json(raw)

    scenes = [
        Scene(
            index=i,
            narration=s["narration"].strip(),
            image_prompt=s["image_prompt"].strip(),
            on_screen_text=s.get("on_screen_text", "").strip().upper(),
        )
        for i, s in enumerate(data["scenes"])
    ]

    return Script(
        title=data["title"].strip(),
        hook=data["hook"].strip(),
        description=data["description"].strip(),
        tags=[t.lower().lstrip("#") for t in data["tags"]][:15],
        scenes=scenes,
    )
