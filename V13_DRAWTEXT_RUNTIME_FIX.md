# V13 FFmpeg drawtext runtime fix

The GitHub Actions runner used by the pipeline can provide an FFmpeg build where `drawtext` is unavailable. The renderer now detects filter support at runtime.

- Default motion graphics use `drawbox` only.
- Word-by-word captions continue to use ASS/libass.
- Legacy text HUDs are skipped when `drawtext` is unavailable.
- The renderer logs the fallback instead of crashing.
- The final difference card remains artwork-first; its text is not baked with `drawtext` in the no-drawtext path.

Regression coverage includes the exact `No such filter: 'drawtext'` failure mode.
