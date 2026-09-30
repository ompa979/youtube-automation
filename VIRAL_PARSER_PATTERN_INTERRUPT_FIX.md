# Viral Parser Pattern Interrupt Fix

Fixed a Viral V2 runtime crash where the JSON parser correctly detected the six viral action types but then looked them up in the legacy exam-only motion/camera/SFX defaults map.

Previous failure:
- `KeyError: 'pattern_interrupt'`

Fix:
- Added deterministic defaults for `pattern_interrupt`, `tension`, `transformation`, `payoff`, and `loop`.
- Kept the existing `mechanism` defaults unchanged because that role is shared.
- Added a regression test that parses the complete six-scene viral action contract and verifies the resulting motion/camera/SFX mappings.

No topic-selection, thumbnail, Cloudflare, YouTube credentials, upload, or exam-mode logic was changed.
