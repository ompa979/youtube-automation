"""YouTube Data API v3 uploader with thumbnail upload + pinned comment.

After a successful video upload this module:
  1. Sets the thumbnail (if thumbnail.jpg exists in OUT_DIR)
  2. Posts a pinned comment with scene timestamps
  3. Pins that comment via the YouTube API

All post-upload steps are non-fatal — a failure in any of them does not
abort the pipeline or count as a failed upload.
"""
from __future__ import annotations

import time
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from .config import YouTubeCredentials, OUT_DIR
from .quota import pick_project, record_upload
from .script_gen import Script


def _creds_from_payload(payload: dict) -> Credentials:
    # Use only the scopes granted when this refresh token was generated.
    # Requesting additional scopes (like force-ssl) during token refresh causes Google OAuth
    # to throw 'invalid_scope: Bad Request' and block the entire upload.
    scopes = payload.get("scopes")
    if not scopes:
        scopes = ["https://www.googleapis.com/auth/youtube.upload"]
    elif isinstance(scopes, str):
        scopes = [scopes]
    return Credentials(
        token=payload.get("token"),
        refresh_token=payload["refresh_token"],
        token_uri=payload.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=payload["client_id"],
        client_secret=payload["client_secret"],
        scopes=scopes,
    )


def _verify_thumbnail(yt, video_id: str, expected_url: str | None = None, attempts: int = 3) -> tuple[bool, str]:
    """Verify that *our* custom thumbnail is visible on YouTube.

    A ``videos.list(part=snippet)`` response always contains a thumbnail for a
    video, even when YouTube is still using an automatically generated frame.
    Therefore merely finding a thumbnail URL is NOT proof that ``thumbnails.set``
    succeeded.  When ``thumbnails.set`` returns a thumbnail resource, this check
    requires the same remote URL to be exposed by ``videos.list``.

    We intentionally do not compare image bytes because YouTube may resize or
    re-encode the uploaded JPEG.
    """
    last_error = ""
    for attempt in range(1, attempts + 1):
        try:
            response = yt.videos().list(part="snippet", id=video_id).execute()
            items = response.get("items") or []
            if not items:
                last_error = "video not visible yet via videos.list"
            else:
                thumbs = (items[0].get("snippet") or {}).get("thumbnails") or {}
                urls = [str(v.get("url")) for v in thumbs.values() if v.get("url")]
                if expected_url:
                    if expected_url in urls:
                        return True, "remote thumbnail URL matches thumbnails.set response"
                    last_error = "videos.list thumbnail URLs do not match thumbnails.set response"
                elif urls:
                    # The set call succeeded but returned no usable thumbnail
                    # resource, so do not falsely claim that the custom image is live.
                    last_error = "thumbnails.set returned no thumbnail URL to verify"
                else:
                    last_error = "videos.list returned no thumbnail URL"
        except Exception as exc:
            last_error = str(exc).replace("\n", " ")[:500]

        if attempt < attempts:
            delay = 3 * attempt
            print(f"[upload] thumbnail verification {attempt}/{attempts} not ready; retrying in {delay}s: {last_error}")
            time.sleep(delay)

    return False, last_error or "thumbnail verification failed"


def _set_thumbnail(yt, video_id: str, thumb_path: Path, attempts: int = 4) -> dict:
    """Upload and verify the custom thumbnail.

    Returns a machine-readable status instead of silently swallowing the result:
      VERIFIED             = thumbnails.set succeeded and videos.list sees it
      UPLOADED_UNVERIFIED  = thumbnails.set succeeded but follow-up verification failed
      FAILED_PERMISSION    = YouTube rejected the credential/channel permission
      FAILED               = transient/other failure after retries
      SKIPPED_NO_FILE      = no valid thumbnail was produced locally

    The operation remains non-fatal to the video upload itself, but the final
    upload summary now makes the thumbnail state explicit.
    """
    if not thumb_path.exists() or thumb_path.stat().st_size < 5000:
        print("[upload] THUMBNAIL: SKIPPED_NO_FILE — thumbnail.jpg missing or too small")
        return {"status": "SKIPPED_NO_FILE", "attempts": 0, "error": "missing_or_too_small"}

    _PERMISSION_MARKERS = (
        "doesn't have permissions to upload and set custom video thumbnails",
        "does not have permissions to upload and set custom video thumbnails",
        "insufficientpermissions",
        "insufficient permissions",
    )
    _PERMANENT_MARKERS = _PERMISSION_MARKERS + (
        "invalidimage",
        "mediabodyrequired",
    )

    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            media = MediaFileUpload(str(thumb_path), mimetype="image/jpeg")
            response = yt.thumbnails().set(videoId=video_id, media_body=media).execute()
            items = response.get("items") or [] if isinstance(response, dict) else []
            expected_url = None
            if items:
                thumbnail_resource = items[0] or {}
                # The set response contains the thumbnail resource accepted by YouTube.
                for key in ("maxres", "standard", "high", "medium", "default"):
                    candidate = thumbnail_resource.get(key) or {}
                    if candidate.get("url"):
                        expected_url = candidate["url"]
                        break

            print(f"[upload] thumbnail set accepted: {thumb_path.name} (attempt {attempt})")
            verified, detail = _verify_thumbnail(yt, video_id, expected_url=expected_url)
            if verified:
                print(f"[upload] THUMBNAIL: VERIFIED — {detail}")
                return {"status": "VERIFIED", "attempts": attempt, "error": ""}

            print(f"[!] THUMBNAIL: UPLOADED_UNVERIFIED — {detail}")
            return {"status": "UPLOADED_UNVERIFIED", "attempts": attempt, "error": detail}
        except Exception as exc:
            last_exc = exc
            msg = str(exc).replace("\n", " ")
            lower = msg.lower()
            if any(marker in lower for marker in _PERMISSION_MARKERS):
                print(
                    "[!] THUMBNAIL: FAILED_PERMISSION — YouTube rejected the authenticated "
                    "channel/credential for custom thumbnails. Channel verification/eligibility "
                    "must be fixed in YouTube; retrying the same API call cannot grant permission. "
                    f"Original error: {msg}"
                )
                return {"status": "FAILED_PERMISSION", "attempts": attempt, "error": msg[:1000]}
            if any(marker in lower for marker in _PERMANENT_MARKERS):
                print(f"[!] THUMBNAIL: FAILED — permanent API rejection: {msg}")
                return {"status": "FAILED", "attempts": attempt, "error": msg[:1000]}
            if attempt < attempts:
                delay = 5 * attempt
                print(f"[!] Thumbnail upload attempt {attempt}/{attempts} failed, retrying in {delay}s: {msg}")
                time.sleep(delay)

    msg = str(last_exc).replace("\n", " ")[:1000] if last_exc else "unknown error"
    print(f"[!] THUMBNAIL: FAILED after {attempts} attempts (non-fatal): {msg}")
    return {"status": "FAILED", "attempts": attempts, "error": msg}


def _build_timestamp_comment(script: Script, durations: list[float]) -> str:
    """Build a pinned comment with per-scene timestamps."""
    lines = [f"📚 {script.title}", ""]
    t = 0.0
    for i, (scene, dur) in enumerate(zip(script.scenes, durations)):
        minutes = int(t // 60)
        seconds = int(t % 60)
        ts = f"{minutes}:{seconds:02d}"
        # Use on_screen_text as chapter label if available, else narration preview
        label = scene.on_screen_text.strip() or scene.narration[:40].strip()
        lines.append(f"{ts} — {label}")
        t += dur

    lines += [
        "",
        "— Auto-generated by ExamCracker AI",
    ]
    return "\n".join(lines)


def _post_pinned_comment(yt, video_id: str, text: str) -> str:
    """Post a comment to the video. Returns 'SUCCESS', 'FAILED (AUTH_SCOPE)', or 'FAILED'."""
    try:
        resp = yt.commentThreads().insert(
            part="snippet",
            body={
                "snippet": {
                    "videoId": video_id,
                    "topLevelComment": {
                        "snippet": {"textOriginal": text}
                    },
                }
            },
        ).execute()
        comment_id = resp["snippet"]["topLevelComment"]["id"]
        print(f"[upload] CTA comment posted (id={comment_id})")
        return "SUCCESS"
    except Exception as exc:
        msg = str(exc).lower()
        if "403" in msg and ("insufficient" in msg or "scope" in msg):
            print("[!] COMMENT: FAILED — AUTH_SCOPE (token lacks https://www.googleapis.com/auth/youtube.force-ssl; re-authorization required)")
            return "FAILED (AUTH_SCOPE)"
        print(f"[!] COMMENT: FAILED — {exc}")
        return "FAILED" 


def _ordered_projects(projects: list[YouTubeCredentials]) -> tuple[list[YouTubeCredentials], object]:
    """Return quota-eligible projects in the caller's preferred order."""
    if not projects:
        return [], None
    names = [p.name for p in projects]
    chosen_name, state = pick_project(names)
    if chosen_name is None:
        return [], state
    start = next(i for i, p in enumerate(projects) if p.name == chosen_name)
    return projects[start:] + projects[:start], state


def upload_video(
    video_path: Path,
    script: Script,
    projects: list[YouTubeCredentials],
    privacy: str = "public",
    category_id: str = "27",
    scene_durations: list[float] | None = None,
) -> dict:
    """Upload with automatic per-channel fallback.

    Each YouTube OAuth credential represents an independent channel/account.
    The upload itself is the failover boundary: if one credential fails before a
    video ID is created (including uploadLimitExceeded, quota, auth, or transport
    errors), the next quota-eligible credential is tried. Once a video ID is
    created, thumbnail/comment operations stay on that same channel and remain
    non-fatal.
    """
    ordered, state = _ordered_projects(projects)
    if not ordered:
        raise RuntimeError(
            "All YouTube projects are unavailable or exhausted: "
            "no quota-eligible credential remains."
        )

    body = {
        "snippet": {
            "title": script.title[:100],
            "description": script.description[:4900],
            "tags": script.tags[:15],
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }

    failures: list[str] = []
    for chosen in ordered:
        creds = _creds_from_payload(chosen.payload)
        try:
            print(f"[upload] trying {chosen.name} (channel credential fallback)")
            yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
            media = MediaFileUpload(
                str(video_path),
                mimetype="video/mp4",
                resumable=True,
                chunksize=4 * 1024 * 1024,
            )
            request = yt.videos().insert(part="snippet,status", body=body, media_body=media)
            response = None
            while response is None:
                _, response = request.next_chunk()

            video_id = response["id"]
            record_upload(chosen.name, state)
            url = f"https://youtu.be/{video_id}"
            print(f"[upload] video live: {url} via {chosen.name}")

            # Once YouTube returned a video ID, do not switch channels: the video
            # already exists on this channel. Metadata/thumbnail/comment failures
            # remain non-fatal.
            time.sleep(6)
            thumb_path = OUT_DIR / "thumbnail.jpg"
            thumbnail_result = _set_thumbnail(yt, video_id, thumb_path)
            thumbnail_status = thumbnail_result["status"]

            can_post_comment = any("force-ssl" in s for s in (creds.scopes or []))
            comment_text = (script.pinned_comment or "").strip()
            comment_status = "SKIPPED (AUTH_SCOPE)"
            if can_post_comment:
                if comment_text:
                    comment_status = _post_pinned_comment(yt, video_id, comment_text)
                elif scene_durations:
                    comment_status = _post_pinned_comment(yt, video_id, _build_timestamp_comment(script, scene_durations))
            else:
                print("[upload] Pinned comment skipped: OAuth credentials only have 'youtube.upload' scope. (Re-authorize token with force-ssl scope if you want automated comments).")

            print(f"[upload summary] UPLOAD: SUCCESS | VIDEO: {url} | THUMBNAIL: {thumbnail_status} | CHANNEL_CRED: {chosen.name} | COMMENT: {comment_status}")
            return {
                "video_id": video_id,
                "url": url,
                "project": chosen.name,
                "thumbnail_status": thumbnail_status,
                "thumbnail_error": thumbnail_result.get("error", ""),
            }
        except Exception as exc:
            msg = str(exc).replace("\n", " ")[:1000]
            failures.append(f"{chosen.name}: {msg}")
            print(f"[!] {chosen.name} upload failed — trying next channel credential: {msg}")
            continue

    raise RuntimeError("All YouTube credentials failed: " + " | ".join(failures))
