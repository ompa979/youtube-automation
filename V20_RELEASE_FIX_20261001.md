# V20 Release Fix — 2026-10-01

## Fixed

- V20 QA now measures **creative-canvas motion**, not only hard cuts.
- Static single-image videos with animated text/audio are rejected.
- Single-canvas formats require continuous creative motion and non-dead tail motion.
- Brain Trap countdown remains in the lower HUD and cannot cover the puzzle target.
- Brain Trap reveal uses camera punch/zoom to declared target metadata; no arbitrary circle overlay.
- The first Brain Trap seed metadata is consistent at x=72%, y=43%.
- Release archive is packaged from repository contents, with `.github/` and `pipeline/` at archive root.

## Verification

- `tests/test_v20_feed_engine.py`: 10 passed.
- Existing Brain Trap render QA: PASS.
- Brain Trap render: 1080x1920, 8.0s, zero hard cuts, creative motion active across the render.
- A generated static 1080x1920 MP4 with valid audio is explicitly rejected by the new QA gate.

## Environment note

The complete local test suite could not be collected in the sandbox because the preinstalled environment lacks `google.oauth2`; network access is unavailable here, so dependencies could not be downloaded. The V20-specific suite and visual QA were run successfully.
