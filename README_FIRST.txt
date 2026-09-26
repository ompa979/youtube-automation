FRESH WORKFLOW FIX

Replace:
.github/workflows/generate.yml

with the generate.yml included in this ZIP.

Important:
- The workflow starts with `name: Generate YouTube Short`.
- The verification block is correctly nested under jobs.build.steps.
- No Markdown ``` fences are inside the YAML.
- The old grep for `safe_overlay` has been replaced with checks matching the current TTS implementation.
- Python compile checks run before generation.
- OpenRouter remains the configured script-generation provider through OPENROUTER_API_KEY.
- Edge TTS remains configured with hi-IN-MadhurNeural and hi-IN-SwaraNeural.

This is a workflow patch, not a replacement of the entire repository. Keep your existing pipeline/*.py files.
