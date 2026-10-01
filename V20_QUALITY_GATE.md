# V20 Feed-Native Quality Gate

V20 now treats visual quality as a production invariant, not a post-hoc review.

## Source contracts

| Format | Source contract | Rule |
|---|---|---|
| Brain Trap | `SINGLE_CANVAS` | One generated canvas for the entire Short; continuous zoom/pulse; reveal overlays the same target; return toward frame-0 framing. |
| Optical Illusion | `SINGLE_CANVAS` | One generated canvas; perceptual motion comes from controlled camera movement/overlay rather than scene replacement. |
| Satisfying | `REAL_MOTION_VIDEO` | One real motion-video source. V20 refuses to substitute a still image. Pexels video acquisition is used when `PEXELS_API_KEY` is configured. |
| Interactive Choice | `SINGLE_CANVAS` | One 9:16 four-choice HUD canvas; choices remain spatially coherent. |
| Micro Loop | `SINGLE_CANVAS` | One visual source with deterministic forward/reverse motion and seam validation. |

## Audio contract

Every V20 render starts with a low-level audio bed. Timed SFX are layered independently so no FFmpeg audio pad is reused. The payoff region ducks the bed before the impact and restores the ambient tail afterward.

## Automated rejection

`pipeline.quality.assert_v20_quality()` runs **after rendering and before `upload_video()`**.

It checks:

- 1080×1920 output
- >=29 FPS
- 5.5–9.5 second duration
- audio stream exists
- hard-cut count for single-canvas formats
- measurable real motion for Satisfying
- frame-0/frame-end seam error for Micro Loop

A failed gate raises `V20 QA REJECTED` and the video is not uploaded.

## Motion footage

Satisfying/destruction clips use `fetch_v20_motion_video()` and the Pexels video API. V20 deliberately does not fall back to a still image because camera zoom on a photograph is not equivalent to physical material motion.

The seed workflow therefore expects:

```text
PEXELS_API_KEY
```

as a GitHub Actions secret for Satisfying seeds.
