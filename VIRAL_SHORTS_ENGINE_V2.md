# Viral Shorts Engine V2

## Purpose

A separate broad-audience Shorts mode for topics with stronger curiosity, human consequence, novelty, and visual storytelling potential. Exam mode remains the default scheduled mode unless `CONTENT_MODE=viral` is selected.

## Content pillars

- Psychology & human behaviour
- Money & personal finance (conceptual education, not personalised advice)
- AI & future technology
- Career & work
- Motivation & discipline
- Everyday science
- History & stories
- Social behaviour

## Selection pipeline

1. Build a candidate pool across enabled viral niches.
2. Score candidates with a 100-point viral-fit model.
3. Apply a production gate (`MIN_VIRAL_SCORE`, default 62).
4. Use trend/search signals only as supporting inputs.
5. Select a topic that is recent enough, teachable, visually clear, and not repeated.
6. Log the top board for inspection before generation.

### Viral-fit dimensions

- Broad audience appeal
- Curiosity gap
- Emotional consequence
- Visual potential
- Novelty / surprise
- Clarity / speed
- Concrete mechanism or consequence
- Risk / genericity penalties

## Script architecture

Exactly six beats:

1. `pattern_interrupt` — 0–1.5s
2. `tension` — 1.5–4.5s
3. `mechanism` — 4.5–9s
4. `transformation` — 9–14s
5. `payoff` — 14–21s
6. `loop` — 21–27s

Target 60–85 spoken words; hard cap 100. Viral mode does not add a spoken CTA. The interaction prompt is placed in the pinned comment / description.

## Visual system

Every scene must contain a visual event: move, reveal, transform, split, build, zoom, contrast, or consequence. AI artwork is treated as a story layer, not as wallpaper.

Thumbnail copy is 2–4 words plus a mechanism clarifier. Thumbnails are generated natively at 2160×3840 (9:16) with a center-safe 4:5 region.

## Cloudflare failover

Scenes and thumbnails use:

`CLOUDFLARE_ACCOUNT_ID` → `_2` → `_3` → `_4`

On 429, transport, or unusable-image errors, the next account is tried. A procedural concept fallback is used only when all configured accounts fail.

## YouTube channel failover

The uploader uses the selected credential prefix and rotates through `_1` … `_19`. A channel is considered successful only after the video upload succeeds. Thumbnail/comment operations remain associated with that successful channel.

## Modes

### Exam mode

`CONTENT_MODE=exam` (default). Existing exam topic plan and scheduled behaviour remain intact.

### Viral mode

`CONTENT_MODE=viral`. Uses `viral_content_plan.json`, viral topic selection, viral script structure and broad-audience creative packaging.

## Dry run

Use:

```bash
python -m pipeline.generate --count 1 --dry-run
```

or set `DRY_RUN=true`.

Dry run renders the video and thumbnail but does not upload to YouTube or mutate persistent YouTube state.

## GitHub Actions

Manual dispatch exposes:

- `content_mode`: `exam` or `viral`
- `credential_group`: `main` or `viral`
- `dry_run`: safe render-only mode
- `test_mode`: `fast` or `full`

Scheduled runs remain in exam mode unless the workflow is intentionally changed.
