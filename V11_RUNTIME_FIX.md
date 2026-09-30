# V11 Runtime Fix

- Fixed Gemini schema-fallback scene recovery: nested `script/data/result/content` scene arrays are unwrapped.
- If the JSON repair call returns an empty scene list, the pipeline performs one clean six-scene generation before rejecting the topic.
- Preserved blocking factual QA; no facts are invented during deterministic recovery.
- Exam-only topic scoring no longer downgrades a valid exam-lane topic merely because the title lacks an explicit exam acronym.
- Low-value generic topic candidates are gated out before selection.
- Trend remains the first selector key, followed by SEO, exam fit, value, and visual quality.
