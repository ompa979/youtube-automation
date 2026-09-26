# Background Music (Optimization #6)

Two tracks are already included, generated locally with ffmpeg's audio
synthesis filters (sine-wave pads + tremolo + subtle noise/echo) — 100%
royalty-free, no attribution needed, no external download required:

- `ambient_soft_1.mp3` — Dm→Bb→F→C progression, airy pad + shimmer, ~88s
- `lofi_study_1.mp3` — Am→F→C→G progression, warmer pad + light vinyl crackle, ~80s

The pipeline picks the first `.mp3` alphabetically (currently `ambient_soft_1.mp3`).
Volume is auto-ducked to 3.5% in the final mix so it never competes with the voice,
and the track loops (`aloop`) to cover the full video length regardless of its
own length.

## Want real produced music instead?
Drop your own MP3s in here (same naming convention) and they'll be picked up
automatically:
- https://pixabay.com/music/search/lofi/
- https://pixabay.com/music/search/ambient/

## Naming convention:
  lofi_study_1.mp3
  lofi_study_2.mp3
  ambient_soft_1.mp3

Add multiple tracks — the pipeline rotates through them in future updates.
