"""Evaluate V20 videos whose 72-hour observation window has closed."""
from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timezone

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from pipeline.v20_telemetry import DB_FILE, OBSERVATION_HOURS, evaluate_v20, init_telemetry_db


def main() -> int:
    raw = os.getenv("YT_CREDS_2", "").strip()
    if not raw:
        raise RuntimeError("YT_CREDS_2 is required for V20 telemetry")
    payload = json.loads(base64.b64decode(raw).decode("utf-8")) if not raw.startswith("{") else json.loads(raw)
    scopes = payload.get("scopes") or []
    if isinstance(scopes, str):
        scopes = [scopes]
    if not any("yt-analytics.readonly" in s or s.endswith("/youtube.readonly") for s in scopes):
        print("[v20-telemetry] credential does not advertise YouTube Analytics/readonly scope; nothing evaluated")
        return 0
    creds = Credentials(token=payload.get("token"), refresh_token=payload["refresh_token"], token_uri=payload.get("token_uri", "https://oauth2.googleapis.com/token"), client_id=payload["client_id"], client_secret=payload["client_secret"], scopes=scopes)
    yt = build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False)
    init_telemetry_db()
    import sqlite3
    with sqlite3.connect(DB_FILE) as conn:
        rows = conn.execute("SELECT video_id,published_at FROM v20_shorts_telemetry WHERE evaluated_at IS NULL").fetchall()
    now = datetime.now(timezone.utc)
    evaluated = 0
    for video_id, published_at in rows:
        published = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        if (now - published).total_seconds() < OBSERVATION_HOURS * 3600:
            continue
        result = evaluate_v20(yt, video_id, now=now)
        if result:
            evaluated += 1
            print(f"[v20-telemetry] evaluated {video_id}: feed={result['shorts_feed_views']} search={result['search_views']} views={result['views']} APV={result['average_view_percentage']:.1f}")
    print(f"[v20-telemetry] complete: {evaluated} video(s) evaluated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
