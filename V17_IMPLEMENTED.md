# ExamCracker V17 — Information Design Creative Engine

V17 keeps the existing Gemini → TTS → Cloudflare FLUX → FFmpeg → YouTube pipeline, but replaces the visual packaging layer.

## Creative contract

- Strong first frame: exact topic + mechanism, not subtitle fragments.
- One visual family per Short: the same hero subject/material language is carried across scenes.
- Three visual modes:
  - `concept` — hook/context/mechanism
  - `worked_example` — one concrete example
  - `exam_card` — exam clue and final comparison
- AI artwork is the visual layer. FFmpeg information cards carry the durable teaching text.
- Generic labels such as `WHY THIS MATTERS`, `THE CONTEXT`, `HOW IT WORKS`, and narration fragments such as `requiring immediate` are rejected/replaced by deterministic topic-specific copy.
- V17 uses a 62–80 spoken-word target with a 90-word hard cap.

## Runtime repairs included

- Scene render now has runtime-safe fallback levels: ASS → block subtitle → base + ASS → base video.
- Final comparison drawbox uses fixed pixel dimensions rather than `ih` expressions.
- Google Trends uses the urllib3 compatibility shim inside the topic engine as well as the standalone trends module.
- Trend is now one input to the composite selector instead of a literal first-sort key, so one noisy trend spike cannot dominate the quality board.

## Local smoke test

The repository was rendered offline with six synthetic scenes through the V17 renderer. The output was 1080x1920 H.264/AAC and the 16:9 thumbnail engine also completed.
