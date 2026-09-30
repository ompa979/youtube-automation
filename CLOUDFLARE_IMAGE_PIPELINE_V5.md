# Cloudflare Image Pipeline V5 — Final

## Active AI image generation
Cloudflare Workers AI + `@cf/black-forest-labs/flux-1-schnell` is the active AI image provider for:
- vertical 9:16 scene visuals used by Shorts
- 16:9 thumbnail hero backgrounds

## Gemini status
Gemini remains used for script/text generation. Gemini image generation is **disabled in the active production route** because it was not reliably generating images in this environment. Its legacy image-generation function remains in `pipeline/visuals.py` for a future explicit opt-in.

## Active fallback order for scene images
1. Cloudflare FLUX.1 Schnell
2. Pexels, when `PEXELS_API_KEY` exists
3. Procedural backdrop

Pollinations is no longer called by the active scene-image path.

## GitHub Actions secrets
Required:
- `CLOUDFLARE_ACCOUNT_ID`
- `CLOUDFLARE_API_TOKEN`
- `GEMINI_API_KEY` (script generation only)

Optional:
- `PEXELS_API_KEY` (stock-image fallback)

## Runtime configuration
- `IMAGE_PROVIDER=cloudflare`
- `CLOUDFLARE_SCENE_IMAGES_ENABLED=true`
- `CLOUDFLARE_SCENE_WIDTH=768`
- `CLOUDFLARE_SCENE_HEIGHT=1365`
- `CLOUDFLARE_IMAGE_MODEL=@cf/black-forest-labs/flux-1-schnell`
- `CLOUDFLARE_IMAGE_STEPS=4`
- `THUMBNAIL_VARIANTS=3`

## Thumbnail pipeline
Each video produces 3 curiosity-first 16:9 thumbnail candidates, composes text/layout locally with Pillow, scores the candidates, and selects the best candidate as `/tmp/out/thumbnail.jpg`.

## Tests
- 100/100 existing thumbnail sanity tests passed.
- 16/16 Cloudflare scene-provider tests passed.
- Total automated tests executed: 116/116 passed.
- Python compile check passed for all pipeline modules.
- GitHub Actions workflow YAML parsed successfully.
- Static audit confirmed Cloudflare is the active scene-image route and Gemini/Pollinations are not invoked from `fetch_scene_image()`.
- Tests use mocked responses only; no secret values are embedded or printed.
