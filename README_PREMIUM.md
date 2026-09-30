# YouTube Automation — ExamCracker V7 Creative Stack

## What changed from the previous version

| Component | Before | Now |
|-----------|--------|-----|
| Script AI | OpenRouter (weak free models) | **Gemini 2.5 Flash** (PRIMARY) → Gemini 1.5 Flash (fallback) |
| TTS | Edge-TTS / gTTS / espeak | **Google Cloud Chirp3-HD** (if key set) → Edge NeerjaNeural → gTTS → eSpeak |
| Images | Cloudflare Workers AI | FLUX.1 Schnell for scenes + FLUX.2 Klein 4B for thumbnails; Gemini image generation is disabled |

## GitHub Secrets — what to set

### Required
| Secret | Value |
|--------|-------|
| `GEMINI_API_KEY` | Your Google AI Studio key (free at aistudio.google.com) |
| `YT_CREDS_1` | Normal/exam YouTube OAuth JSON (base64-encoded) |
| `YT_CREDS_2` | Viral YouTube OAuth JSON (base64-encoded) |

### Optional but recommended (free-tier voice upgrade)
| Secret | Value |
|--------|-------|
| `GOOGLE_CLOUD_TTS_KEY` | Google Cloud API key with "Cloud Text-to-Speech API" enabled |

**How to get a Google Cloud TTS key (free — 1M chars/month):**
1. Go to console.cloud.google.com → Create/select a project
2. APIs & Services → Enable → search "Cloud Text-to-Speech API" → Enable
3. APIs & Services → Credentials → Create Credentials → API Key
4. Add it as `GOOGLE_CLOUD_TTS_KEY` in GitHub Secrets
5. Set `TTS_PROVIDER: google_cloud` in the workflow env block

**Best voices:**
- Female: `en-IN-Chirp3-HD-Achernar` (default)
- Male: `en-IN-Chirp3-HD-Fenrir`

### Secrets you can DELETE
- `OPENROUTER_API_KEY` — no longer used
- `POLLINATIONS_API_KEY` — no longer used for active image generation
- `OPENROUTER_MODEL` — no longer used
- `OPENROUTER_TTS_MODEL` — no longer used
- `TTS_PROVIDER` secret — now set directly in the workflow file

### Keep these
- `GEMINI_API_KEY`
- `PEXELS_API_KEY`
- `YT_CREDS_1`
- `LANGUAGES_ENABLED`
- `TTS_LANGUAGE`
- `TTS_VOICE`
