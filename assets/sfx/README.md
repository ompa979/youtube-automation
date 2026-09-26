# Transition SFX (Optimization #6)

`whoosh.mp3` is a synthesized, royalty-free bandpass-filtered noise burst
used as a subtle "whoosh" under every scene cut. Generated locally with
ffmpeg — no external download, no licensing risk.

The pipeline picks the first `.mp3`/`.wav` found here and layers a
delayed, low-volume (0.22) copy of it at the timestamp of every crossfade
transition (see `_pick_sfx()` / `assemble_video()` in `pipeline/render.py`).

Drop in your own whoosh/swoosh SFX here (same volume ballpark) to replace it.
