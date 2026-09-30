# Viral Mode Usage

## GitHub Actions

1. Open **Actions → ExamCracker YouTube Generator → Run workflow**.
2. Set `content_mode = viral`.
3. Viral uploads use `YT_CREDS_2` by default; normal/exam uploads use `YT_CREDS_1`.
4. First use `dry_run = true`.
5. Use `test_mode = fast` for normal runs; `full` is optional before major changes.
6. Review the generated artifact. Then run again with `dry_run = false` for publishing.

## Local PowerShell

```powershell
$env:CONTENT_MODE="viral"
$env:VIRAL_CONTENT_ONLY="true"
$env:EXAM_ONLY="false"
$env:YOUTUBE_CREDENTIAL_PREFIX="YT_CREDS"
$env:YOUTUBE_CREDENTIAL_INDICES="2"
python -m pipeline.generate --count 1 --dry-run
```

For exam mode, omit these overrides or set `CONTENT_MODE=exam`.

## Required channel secrets

```text
YT_CREDS_1   # normal/exam channel
YT_CREDS_2   # viral channel
```
Optional: set `YOUTUBE_CREDENTIAL_INDICES="2,3"` to enable an explicit viral fallback pool.

Only configure the channels you actually own/manage. Never commit OAuth client secrets or token JSON files to Git.
