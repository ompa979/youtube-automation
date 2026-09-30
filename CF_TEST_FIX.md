# V10 Cloudflare Test/Runtime Fix

Fixed the six CI failures reported by GitHub Actions.

## Fixes
- `cloudflare_endpoint()` now honors runtime/module overrides used by tests while still reading GitHub Actions environment secrets in production.
- Cloudflare credential resolution now distinguishes imported production credentials from explicit runtime/test overrides.
- `generate_background()` correctly returns `(None, "local")` when Cloudflare credentials are explicitly disabled, even if CI has Cloudflare secrets in its environment.
- Existing FLUX.1/FLUX.2 payload contracts are unchanged.

## Verification
- `python -m pytest -q tests/test_cloudflare_scene_provider.py tests/test_thumbnail_engine_100.py` -> 119 passed
- Full suite: **268 passed in 3.39s**
