# V12 Script Runtime Fix

Fixes observed in the 2026-09-30 GitHub Actions run.

## Changes
- Script hard cap aligned to 80 spoken words.
- Prompt now targets 62–74 words and hard caps at 80.
- Failed scripts now receive up to 2 targeted repair passes instead of only 1.
- A second repair pass is allowed for length, style, structure, and factual-QA failures; factual issues remain blocking until fixed.
- Final post-polish QA and fact-check prevent the polish step from reintroducing a violation.
- Sensational-language detection was narrowed so legitimate technical uses such as `never` or `illegal` are not rejected solely by a broad word match.
- Existing A/B/game-show restrictions remain active.

## Validation
- pytest: 273 passed
