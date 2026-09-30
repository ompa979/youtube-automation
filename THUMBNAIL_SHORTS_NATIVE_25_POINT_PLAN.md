# ExamCracker Shorts-Native Thumbnail Hit-Rate Program — 25 Points

Scope: **thumbnail generation only**. The Shorts video scene pipeline, script generation, TTS, topic selection, SEO, scheduler, and video rendering remain unchanged.

## 25-point program
1. 9:16-native canvas for Shorts.
2. Master output: 2160×3840 JPG.
3. Center-safe 4:5 composition so important content survives narrower channel-page crops.
4. 2–4 word concept headline.
5. Short mechanism/result subline.
6. No generic quiz slogans.
7. No “REVEAL”, “KEY DIFFERENCE”, “QUICK TEST”, countdown HUDs, or giant question marks.
8. Topic-specific copy mapping.
9. TCP handshake specifically maps to `3-WAY HANDSHAKE` + `SYN → SYN-ACK → ACK`.
10. Exact visual metaphor for the topic.
11. One dominant hero subject.
12. Hero and typography occupy opposite sides.
13. AI prompt protects the text side.
14. Final typography is rendered by Pillow, never by the image model.
15. Large mobile-first headline sizing.
16. Maximum two headline lines.
17. High-contrast text with restrained stroke/shadow, no opaque card.
18. Small exam identity tag.
19. Five materially different candidates per Short.
20. Deterministic seeded variation.
21. Automatic text-zone quietness measurement.
22. Candidate scoring checks both 9:16 and center-safe 4:5 readability.
23. When all Cloudflare thumbnail accounts fail, use a designed concept-specific procedural hero instead of a random video frame.
24. Thumbnail AI failover tries Cloudflare account 1 → 2 → 3 → 4, without exposing tokens.
25. Save a thumbnail manifest containing selected candidate, score, copy, background provider, canvas and safe-area metadata.

## Cloudflare thumbnail secret contract

GitHub Actions supports these four independent credential slots:

- `CLOUDFLARE_ACCOUNT_ID` / `CLOUDFLARE_API_TOKEN`
- `CLOUDFLARE_ACCOUNT_ID_2` / `CLOUDFLARE_API_TOKEN_2`
- `CLOUDFLARE_ACCOUNT_ID_3` / `CLOUDFLARE_API_TOKEN_3`
- `CLOUDFLARE_ACCOUNT_ID_4` / `CLOUDFLARE_API_TOKEN_4`

The pool is used **only by the thumbnail image adapter**. It does not alter scene generation.

## Output contract

- Canvas: **2160 × 3840**
- Ratio: **9:16**
- Format: JPG/PNG compatible; pipeline writes JPG
- Core copy stays in the central vertical band
- No critical text at the extreme top/bottom edges
- No random video-frame fallback when AI is unavailable
