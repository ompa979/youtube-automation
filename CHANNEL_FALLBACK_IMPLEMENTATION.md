# Channel + Provider Fallback Implementation

This build keeps the existing Shorts, viral-content, thumbnail, Cloudflare, and dry-run systems intact and strengthens the upload fallback boundary.

## YouTube channels

`YT_CREDS_1` through `YT_CREDS_19` are exposed in GitHub Actions. The generator rotates from the last successful credential, skips quota-exhausted credentials, and the uploader itself retries the next configured channel credential when `videos.insert` fails.

A fallback happens before a YouTube video ID exists. Once a video ID is returned, the pipeline stays on that channel for thumbnail/comment operations; those post-upload operations remain non-fatal.

## Cloudflare thumbnails

The existing thumbnail failover remains: Cloudflare account 1 -> 2 -> 3 -> 4, with FLUX.2 -> FLUX.1 fallback per account. The workflow exposes all four account/token pairs.

## Dry run

Dry run generates script, audio, scenes, video, and Shorts-native thumbnail artifacts but never calls the YouTube upload or post-upload mutation path.
