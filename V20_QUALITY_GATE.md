# V20 Quality Gate

V20 now uses an **adversarial, fail-closed viewer-experience gate**.

The old gate could accept a static AI image because it primarily looked for hard
cuts. The current gate measures the protected creative canvas itself and rejects
static, intermittent, frozen, blank, badly encoded, silent, cut-heavy, or
contract-invalid output.

See `V20_EXTREME_QA.md` for the exact thresholds.
