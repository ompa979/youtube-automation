# ExamCracker Thumbnail Hit-Rate Program — 25 Point Plan

Scope: **thumbnail generation only**. Video scenes, script, TTS, topic selection, SEO, scheduler and YouTube rendering are unchanged.

1. **Concept-first headline** — headline names the exact concept, not a generic challenge.
2. **2–4 word headline rule** — readable at Shorts feed size.
3. **Mechanism subline** — second line explains the mechanism/result in a few words.
4. **No quiz-slogan copy** — remove “Which?”, “Quick Test”, “Reveal”, “Key Difference”, “Can You”, etc.
5. **Topic-specific copy map** — recurring exam concepts get tested, proven thumbnail language.
6. **TCP handshake correction** — `3-WAY HANDSHAKE` + `SYN → SYN-ACK → ACK` instead of the unrelated TCP-vs-UDP label.
7. **Exact visual metaphor** — artwork must show the concept rather than generic education imagery.
8. **Single hero rule** — one dominant object/process, not a collage.
9. **Right/left subject split** — keep the hero on one side and typography on the quieter side.
10. **Automatic text-zone detection** — choose the quieter half from the actual image.
11. **Negative-space preservation** — AI prompt explicitly protects the copy region.
12. **No AI-generated typography** — all words are composited deterministically.
13. **Mobile font sizing** — large bold copy with a two-line ceiling.
14. **High-contrast text** — controlled shadow/stroke without a boxed card.
15. **No giant question mark / countdown HUD** — removes game-show styling.
16. **Exam identity kept small** — exam tag supports context without competing with the idea.
17. **Five candidate concepts** — metaphor, confrontation, journey, macro, editorial variants remain materially different.
18. **Seeded variation** — candidate art uses deterministic seed separation.
19. **Visual scoring** — candidates are ranked using contrast, brightness, edge energy, balance and text-zone quietness.
20. **Copy scoring** — penalties for long, generic, question-heavy or overstuffed thumbnail text.
21. **Subject/text balance check** — prefers a clear separation between hero complexity and typography space.
22. **Procedural concept fallback** — when AI quota is exhausted, generate a topic-specific designed graphic instead of using a random video frame.
23. **Cloudflare account failover** — try account 1, then accounts 2–4 with the same thumbnail model/fallback model.
24. **Provider-failure logging** — each failed account/model is logged without exposing the secret token.
25. **Manifest/audit trail** — selected variant, source, score, copy and composition are stored for later CTR analysis.

## Cloudflare secret contract

The workflow supports:

- `CLOUDFLARE_ACCOUNT_ID` / `CLOUDFLARE_API_TOKEN`
- `CLOUDFLARE_ACCOUNT_ID_2` / `CLOUDFLARE_API_TOKEN_2`
- `CLOUDFLARE_ACCOUNT_ID_3` / `CLOUDFLARE_API_TOKEN_3`
- `CLOUDFLARE_ACCOUNT_ID_4` / `CLOUDFLARE_API_TOKEN_4`

The pool is **thumbnail-only**. A quota failure on one account moves to the next configured account before the local procedural fallback is used.
