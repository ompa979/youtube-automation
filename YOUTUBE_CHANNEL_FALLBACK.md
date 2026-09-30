# YouTube Channel Fallback

The production uploader supports multiple YouTube OAuth credentials. Each `YT_CREDS_N` secret represents a channel/account authorized by its own OAuth token. In the default setup, `YT_CREDS_1` is the normal/exam channel and `YT_CREDS_2` is the viral channel.

## GitHub Actions

The workflow exposes the shared `YT_CREDS_N` namespace. By default, normal/exam mode uses `YT_CREDS_1` and viral mode uses `YT_CREDS_2`. For an explicit fallback pool, set `YOUTUBE_CREDENTIAL_INDICES="2,3"` (or another comma-separated list).

## Fallback behavior

1. Pick the next quota-eligible credential in rotation order.
2. Try the actual `videos.insert` upload.
3. On upload failure — including `uploadLimitExceeded`, quota, authentication, permission, or transport failures — try the next configured credential.
4. When a video ID is returned, stop channel failover. Thumbnail and comment operations stay on that same channel.
5. If every configured credential fails, the job fails with a compact summary of each credential's error.

## Dry run

`--dry-run` never contacts YouTube for upload, thumbnail, or comments, so no channel fallback occurs in dry-run mode.
