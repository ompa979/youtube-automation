# v18 — Channel audit implementation (complete project)

| # | Audit finding | Files | Change |
|---|---|---|---|
| 1 | 0 comments | script_gen.py, upload.py, render.py | Prompt forces a comment-CTA in the last scene + `pinned_comment`; `_ensure_cta()` guarantees it. Upload posts that CTA as the first comment (replaces useless timestamps). Outro card phrases are all comment prompts. |
| 2 | Wrong fact shipped | script_gen.py, generate.py | Fact-check is BLOCKING: issue -> repair -> `ScriptRejected`. Deterministic guard for "RBI CEO"/named office-holders. Rejected topics are skipped, not retried forever. |
| 3 | RBI Grade B underperforms | content_plan.json, generate.py | Per-niche `weight` + weighted rotation: IT 2, Reasoning 2, Awareness 2, RBI 1, English 1 (RBI = 1/8 of videos, was 1/5). Edit weights in content_plan.json. |
| 4 | 30s+ underperforms | script_gen.py, quality.py | 45-80 words, 3-5 scenes enforced in prompt + QA (quality.py cap now 36s incl. title/hook). |
| 5 | No exam in title | script_gen.py | Exam name forced to the front after SEO, <=65 chars. |

## Manual steps
* Unpublish the "CEO of RBI" video in Studio.
* The YouTube API cannot pin comments (the old `setModerationStatus` call never pinned). The CTA is posted as the channel's first comment; pin it manually if desired.
* Old videos are unchanged; results should show in the next 1-2 weeks of uploads.
