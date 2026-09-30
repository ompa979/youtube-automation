# Viral QA Content-Mode Fix

Fixed the live failure:
`_v6_qa_all() takes 3 positional arguments but 4 were given`.

Changes:
- `_v6_qa_all()` now accepts `content_mode` and passes it to `validate_script`.
- Viral mode uses its own 6-scene sequence: pattern_interrupt, tension, mechanism, transformation, payoff, loop.
- Viral mode no longer applies the exam-only final-difference QA rule.
- Viral mode is still protected from A/B quiz language and generic stop/wait hooks.
- Viral finalization no longer forces an exam name into the title.
- `_v6_to_script()` recognizes the viral scene action types so the viral prompt is not converted into exam scene roles.

Validation performed:
- `python -m py_compile pipeline/script_gen.py pipeline/generate.py` PASS
- source-level signature and content-mode routing check PASS
