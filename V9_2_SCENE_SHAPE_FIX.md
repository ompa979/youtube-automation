# V9.2 — Runtime Scene-Shape Recovery

## Fixed
- When Gemini response-schema fallback returns valid JSON with fewer/more than 6 scenes, the pipeline no longer crashes with `V6 requires exactly 6 scenes`.
- Added a dedicated JSON repair pass that normalizes the draft to the required six roles:
  1. hook
  2. context
  3. mechanism
  4. example
  5. exam_takeaway
  6. difference_card
- The repair preserves existing facts and wording and explicitly forbids adding unsupported facts, A/B quiz framing, countdowns, or generic CTA filler.
- The same safe conversion is used for the normal draft and the explicit repair pass.

## Factual safety
- Cross-model fact checking remains blocking.
- A factual error still rejects the candidate topic and moves the scheduler to the next candidate.
- No factual-error gate was weakened to accommodate the scene-shape repair.

## Regression test
- Added `tests/test_scene_shape_recovery.py` covering a 5-scene malformed draft and verifying deterministic recovery to exactly 6 scenes.

## Validation
- Full offline test suite: 261 passed.
- Python compileall: passed.
