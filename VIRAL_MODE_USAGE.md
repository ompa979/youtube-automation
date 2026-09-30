# Viral Mode Usage

## GitHub Actions

1. Open **Actions → ExamCracker YouTube Generator → Run workflow**.
2. Set `content_mode = viral`.
3. Set `credential_group = viral` if the viral channel uses `VIRAL_YT_CREDS_1...` secrets.
4. First use `dry_run = true`.
5. Use `test_mode = fast` for normal runs; `full` is optional before major changes.
6. Review the generated artifact. Then run again with `dry_run = false` for publishing.

## Local PowerShell

```powershell
$env:CONTENT_MODE="viral"
$env:VIRAL_CONTENT_ONLY="true"
$env:EXAM_ONLY="false"
$env:YOUTUBE_CREDENTIAL_PREFIX="VIRAL_YT_CREDS"
python -m pipeline.generate --count 1 --dry-run
```

For exam mode, omit these overrides or set `CONTENT_MODE=exam`.

## Required viral-channel secrets

```text
VIRAL_YT_CREDS_1
VIRAL_YT_CREDS_2
...
VIRAL_YT_CREDS_19
```

Only configure the channels you actually own/manage. Never commit OAuth client secrets or token JSON files to Git.
