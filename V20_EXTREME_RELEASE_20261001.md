# V20 Extreme Release — 2026-10-01

## Status
FAIL-CLOSED / EXTREME QA

## V20 test result
20 V20 tests passed.

## Production Brain Trap smoke result
- 1080x1920
- 30 FPS
- 8.000 seconds
- H.264 + AAC
- hard cuts: 0
- mean creative motion: 5.87
- p10 motion: 2.59
- active motion: 99.6%
- final-20% motion: 8.41
- maximum freeze: 1 frame
- loop error: 2.70
- audio mean: -40.2 dB

## Release rules
No V20 upload is allowed to bypass `verify_v20_spec()` and
`assert_v20_quality()`.

The full repository pytest collection still requires the packages listed in
`requirements.txt` (the current sandbox lacks `google.oauth2`). The V20 suite
is dependency-complete and passed 20/20 here.
