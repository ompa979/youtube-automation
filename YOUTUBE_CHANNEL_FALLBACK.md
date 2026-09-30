# YouTube Channel Fallback

The production uploader supports multiple YouTube OAuth credentials. Each `YT_CREDS_N` secret represents a channel/account authorized by its own OAuth token.

## GitHub Actions

The workflow exposes `YT_CREDS_1` through `YT_CREDS_19`. Configure only the credentials you actually have. The upload path starts from the last successful credential and rotates through the remaining configured credentials.

## Fallback behavior

1. Pick the next quota-eligible credential in rotation order.
2. Try the actual `videos.insert` upload.
3. On upload failure — including `uploadLimitExceeded`, quota, authentication, permission, or transport failures — try the next configured credential.
4. When a video ID is returned, stop channel failover. Thumbnail and comment operations stay on that same channel.
5. If every configured credential fails, the job fails with a compact summary of each credential's error.

## Dry run

`--dry-run` never contacts YouTube for upload, thumbnail, or comments, so no channel fallback occurs in dry-run mode.
