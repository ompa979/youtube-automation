# YouTube Thumbnail Upload + Verification Fix

Implemented in the uploader without changing the V18 thumbnail design engine.

## What changed

1. `pipeline/upload.py` still uploads `/tmp/out/thumbnail.jpg` with
   `youtube.thumbnails().set()` after `videos.insert()` returns the video ID.
2. A successful API call is no longer treated as the end of the operation.
3. The uploader reads the thumbnail URL returned by `thumbnails.set()` and then
   calls `videos.list(part="snippet", id=VIDEO_ID)` to verify that the same URL
   is visible on the YouTube video.
4. The verifier does **not** treat YouTube's automatically generated thumbnail
   as proof that the custom thumbnail was uploaded.
5. Permission failures are explicitly reported as `FAILED_PERMISSION` and are
   not retried indefinitely.
6. The final upload line now includes the thumbnail state, for example:

   `UPLOAD: SUCCESS | VIDEO: ... | THUMBNAIL: VERIFIED | CHANNEL_CRED: yt_project_2 | COMMENT: SUCCESS`

   or:

   `UPLOAD: SUCCESS | VIDEO: ... | THUMBNAIL: FAILED_PERMISSION | CHANNEL_CRED: yt_project_2 | COMMENT: ...`

## Important limitation

If YouTube returns `403 forbidden` stating that the authenticated user does not
have permission to upload/set custom thumbnails, code cannot grant that channel
permission. The channel must first be eligible/verified in YouTube. Once the
credential has that capability, the same uploader will automatically upload and
verify the generated thumbnail.

## Regression coverage

`tests/test_thumbnail_upload_verification.py` covers:
- successful upload + remote URL verification;
- prevention of a false positive when only YouTube's generated thumbnail is visible;
- explicit permission-failure reporting.
