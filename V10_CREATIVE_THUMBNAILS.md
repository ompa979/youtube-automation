# V10 Creative Thumbnail System

## What changed

V10 replaces the old fixed-layout thumbnail system with an **art-directed, image-first workflow**:

1. Build a creative brief from the topic.
2. Generate five materially different hero-art concepts.
3. Use Cloudflare FLUX.2 Klein 4B for thumbnail artwork.
4. Keep the AI image completely text-free.
5. Analyze the generated artwork for a real quiet text-safe zone.
6. Add the headline only after the image is known.
7. Rank candidates using visual energy + quiet-zone readability.
8. Keep all five candidates and a `manifest.json` for audit/CTR experiments.

The title remains SEO-oriented. The thumbnail is deliberately short (normally 2–5 words) and is not a quiz-show card.

## Five creative modes

- visual metaphor
- confrontation
- journey
- macro mechanism
- editorial human reaction

The style is automatically adapted for finance/banking, IT, history/polity, geography, and science topics.

## Topic radar

Selection order is now literal:

**Trend → SEO → Exam Fit → Value → Visual**

Trend data uses recent Google Trends interest plus short-term momentum. If Trends is unavailable, the selector uses a conservative neutral score rather than treating an outage as a true trend score of zero.

Low-value topics are gated out before publication.

## Cloudflare split

- Scene images: `@cf/black-forest-labs/flux-1-schnell`
- Thumbnail hero art: `@cf/black-forest-labs/flux-2-klein-4b`

The adapters intentionally use different request schemas because the two Workers AI models do not accept the same fields.
