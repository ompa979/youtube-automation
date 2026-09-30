# V14 FFmpeg setup fix

## Problem
GitHub Actions was failing before the pipeline started at `FedericoCarboni/setup-ffmpeg@v3` with `TypeError: fetch failed`.

## Fix
The workflow no longer uses `FedericoCarboni/setup-ffmpeg@v3`.

The new `Verify FFmpeg` step:
1. Uses the Ubuntu runner's existing `ffmpeg` when available.
2. Installs `ffmpeg` with `apt-get` only when it is missing.
3. Prints the detected FFmpeg version.
4. Prints the availability of `ass`, `drawbox`, and `drawtext` filters.

This avoids an unnecessary third-party download action and removes the `fetch failed` failure point.

## Validation
- `python -m pytest -q`: 275 passed.
- Workflow YAML parsed successfully.
- Local FFmpeg version verified.
- `ass`, `drawbox`, and `drawtext` filters verified in the local FFmpeg build.
