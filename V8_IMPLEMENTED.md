# V8 Creative Implementation

## Core changes

### 1. Thumbnail composition
- AI hero art is generated independently from typography.
- Thumbnail compositor now detects the quieter half of the image using edge-density and places text in that safe zone.
- Text is dynamically resized to fit within a two-line maximum.
- Hero area is protected from headline/subline/badge overlays.
- 1280x720 output with compact copy and one visual cue.
- Three thumbnail variants are generated and ranked.

### 2. Audio
- Voice mastering: high-pass + compression + loudness normalization + limiter.
- Targeted voice/master around -12.5 LUFS before final mix.
- Final video mix targets about -13 LUFS with -1 dBTP ceiling.
- Voice mix gain increased to 2.0x.
- Background music lowered to 0.015 and SFX reduced so narration remains dominant.

### 3. Content
- Existing V7 value-first script architecture retained.
- Final sixth scene is now a visual `difference_card` comparison rather than a quiz/game CTA.
- Final comparison scene is forced to use side-by-side visual composition with minimal overlay.
- Legacy A/B/countdown/STOP language is removed from the active generation contract.
- Pinned comment is rebuilt from the final teaching arc so legacy A/B CTAs cannot leak through.

### 4. Topic discovery
- Discovery order is explicitly:
  1. Trend Score
  2. SEO Score
  3. Exam Fit
  4. Value Density
  5. Visual Potential
- Trend/SEO scores are 0-100 and shown first in scheduler logs.
- `EXAM_ONLY=true` is a hard safety rail. Misconfigured `NICHES_ENABLED` cannot fall back to lifestyle topics.
- Topic board is persisted to `.topic_intelligence.json` for audit.

### 5. GitHub Actions
- Preflight runs the complete pytest suite.
- V8 creative contract is verified before generation.
- Existing Cloudflare FLUX image generation secrets remain the only image-provider secrets required.

## Verification
- Full test suite: 260 passed.
- Dedicated thumbnail sanity suite: 100 passed.
- Audio smoke loudness check: approximately -13.2 LUFS integrated after mastering.
- Thumbnail smoke: 1280x720 JPEG validated.
