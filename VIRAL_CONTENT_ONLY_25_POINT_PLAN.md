# ExamCracker — Viral-Content-Only 25-Point Program

This program optimizes for **viral-friendly educational content**, not a promise of virality. It keeps the channel exam-focused and rejects weak topic shapes before generation whenever a sufficiently large candidate pool exists.

1. Exam-only content gate.
2. Minimum viral-fit gate: 62/100 by default.
3. Curiosity gap required.
4. Prefer contrast/head-to-head topics.
5. Prefer common-mistake/trap topics.
6. Prefer counterintuitive “why” topics.
7. Prefer time-saving shortcuts when factually valid.
8. Prefer visible mechanisms: flows, tables, queries, layers, trees, formulas.
9. Prefer a concrete consequence or exam decision.
10. Prefer one clean concept over broad chapters.
11. Reject generic definitions when a stronger angle exists.
12. Reject broad “overview” framing.
13. Reject filler facts with no mechanism or payoff.
14. Reject unsupported sensational wording.
15. Avoid fake urgency and empty clickbait.
16. Hook with the consequence, contradiction, or mistake — not “Hello guys”.
17. Give the minimum setup needed for the viewer to predict the result.
18. Reveal the misconception before the explanation becomes long.
19. Use exactly one concrete example per Short.
20. Finish with one exam trap or decision rule.
21. Keep spoken script in the 45–65 word content target for this viral-content mode.
22. Do not force an A/B game or countdown unless the concept itself naturally supports it.
23. Keep topic-title, script, scene visuals, and thumbnail concept aligned.
24. Score and log viral-fit separately from trend score so a trend spike cannot masquerade as content quality.
25. When no candidate meets the strict viral gate in a production-sized board, fail instead of publishing a weak topic.

## Production switches

```text
VIRAL_CONTENT_ONLY=true
MIN_VIRAL_SCORE=62
```

The existing thumbnail, TTS, rendering, Cloudflare failover, and upload infrastructure are intentionally outside this content-only change.
