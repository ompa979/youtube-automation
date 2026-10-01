# V20 Extreme QA — Fail Closed

This is the pre-upload gate for V20. It is intentionally stricter than ordinary
container validation. **A technically valid MP4 is not sufficient.**

## Hard rejection rules

### Container / encode
- exactly one H.264 video stream
- exactly one AAC audio stream
- 1080x1920
- 29.5–30.5 FPS
- declared format duration within ±0.15 s
- OpenCV must decode essentially every probed frame
- measurable audio; mean volume below -45 dB is rejected

### Visual integrity
- no scene-wide hard cuts
- no excessive near-black frames
- no excessive near-white frames
- no missing/undecodable frame run

### Creative motion
For `BRAIN_TRAP`, `OPTICAL_ILLUSION`, `INTERACTIVE_CHOICE`, and `MICRO_LOOP`:
- motion is measured inside the creative canvas, excluding hook/HUD zones
- mean creative motion >= 1.25
- 10th percentile motion >= 0.50
- 25th percentile motion >= 1.00
- >=95% of inter-frame samples must contain meaningful motion
- first 10% must contain meaningful motion
- final 20% must retain meaningful motion
- no freeze longer than 0.20 s

For `SATISFYING`:
- real motion-video source is mandatory
- mean motion >= 1.50
- 10th percentile motion >= 0.35
- no freeze longer than 0.50 s

### Micro-loop
- blurred first/last-frame seam error <= 18

### Creative contract
- V20 must target Shorts Feed
- search intent must be false
- canvas formats must be `SINGLE_CANVAS`
- satisfying must be `REAL_MOTION_VIDEO`
- Brain Trap `PUNCH_ZOOM_TARGET` requires an explicit target
- target must stay in the safe creative region and away from the center
- AI prompts cannot request guessed bounding circles/boxes

## Philosophy
The gate is **fail closed**. If the pipeline cannot prove that the artifact satisfies
the declared contract, upload is blocked.
