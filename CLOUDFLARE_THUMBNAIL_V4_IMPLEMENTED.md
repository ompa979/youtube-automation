# Cloudflare Thumbnail Engine V4

Implemented on top of the Engagement V2/V3 codebase.

## Provider
- Cloudflare Workers AI REST API
- Model: `@cf/black-forest-labs/flux-1-schnell`
- Required GitHub Actions secrets: `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`
- Default steps: 4
- Thumbnail variants: 3

## Behavior
1. Build curiosity-first thumbnail prompt from the exact challenge.
2. Select one of 10 thumbnail archetypes.
3. Request a clean AI hero background from Cloudflare.
4. Render all text/layout locally with Pillow.
5. Produce 3 candidates and score them.
6. Select the best candidate as `/tmp/out/thumbnail.jpg`.
7. Preserve all candidates and a manifest under `/tmp/out/thumbnail_variants/`.
8. If Cloudflare fails or quota/capacity is exhausted, fall back to the optional generic endpoint and then to the local scene background.

## Testing
- 100/100 thumbnail unit/sanity cases passed.
- Full Python compile passed.
- Mocked Cloudflare REST integration passed.
- 3-variant 1280x720 compositor integration passed.
- GitHub Actions workflow YAML parsed successfully.
- Credential-safety scan passed.

## Live provider limitation
The implementation environment does not have access to the user's Cloudflare secret values, so a real paid/quota-consuming Cloudflare request was **not** executed here. The GitHub Actions job is wired to use the two repository secrets when it runs.
