"""V20 telemetry with a strict 72-hour observation gate."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_FILE = Path(__file__).resolve().parent.parent / "v20_telemetry.db"
OBSERVATION_HOURS = 72


def init_telemetry_db() -> None:
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS v20_shorts_telemetry (
            video_id TEXT PRIMARY KEY, tracking_tag TEXT, format TEXT, subtype TEXT,
            variant INTEGER, duration REAL, published_at TEXT,
            observation_window_hours INTEGER DEFAULT 72, evaluated_at TEXT,
            views INTEGER, shorts_feed_views INTEGER, search_views INTEGER,
            average_view_duration REAL, average_view_percentage REAL,
            likes INTEGER, comments INTEGER, shares INTEGER, subscribers_gained INTEGER,
            stayed_to_watch REAL, swiped_away REAL
        )""")
        conn.commit()


def record_v20_upload(video_id: str, spec: dict[str, Any], published_at: datetime | None = None) -> None:
    init_telemetry_db()
    published_at = published_at or datetime.now(timezone.utc)
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("""INSERT OR REPLACE INTO v20_shorts_telemetry
            (video_id,tracking_tag,format,subtype,variant,duration,published_at,observation_window_hours)
            VALUES (?,?,?,?,?,?,?,?)""", (video_id, spec["tracking_tag"], spec["format"], spec["subtype"], spec["variant"], spec["duration_seconds"], published_at.isoformat(), OBSERVATION_HOURS))
        conn.commit()


def evaluate_v20(youtube_analytics, video_id: str, now: datetime | None = None) -> dict[str, Any] | None:
    init_telemetry_db()
    now = now or datetime.now(timezone.utc)
    with sqlite3.connect(DB_FILE) as conn:
        row = conn.execute("SELECT published_at FROM v20_shorts_telemetry WHERE video_id=?", (video_id,)).fetchone()
    if not row:
        return None
    published = datetime.fromisoformat(row[0].replace("Z", "+00:00"))
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    if (now - published).total_seconds() < OBSERVATION_HOURS * 3600:
        return None

    start = published.date().isoformat()
    end = now.date().isoformat()
    traffic = youtube_analytics.reports().query(
        ids="channel==MINE", startDate=start, endDate=end, metrics="views",
        dimensions="insightTrafficSourceType", filters=f"video=={video_id}"
    ).execute()
    shorts = search = 0
    for r in traffic.get("rows", []):
        if r[0] == "SHORTS": shorts = int(r[1])
        elif r[0] == "YT_SEARCH": search = int(r[1])

    metrics = youtube_analytics.reports().query(
        ids="channel==MINE", startDate=start, endDate=end,
        metrics="views,averageViewDuration,averageViewPercentage,likes,comments,shares,subscribersGained",
        filters=f"video=={video_id}"
    ).execute()
    values = (metrics.get("rows") or [[0, 0, 0, 0, 0, 0, 0]])[0]
    result = {
        "video_id": video_id, "views": int(values[0]), "shorts_feed_views": shorts, "search_views": search,
        "average_view_duration": float(values[1]), "average_view_percentage": float(values[2]),
        "likes": int(values[3]), "comments": int(values[4]), "shares": int(values[5]), "subscribers_gained": int(values[6]),
        "evaluated_at": now.isoformat(), "observation_window_hours": OBSERVATION_HOURS,
    }
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("""UPDATE v20_shorts_telemetry SET evaluated_at=?,views=?,shorts_feed_views=?,search_views=?,
            average_view_duration=?,average_view_percentage=?,likes=?,comments=?,shares=?,subscribers_gained=? WHERE video_id=?""",
            (result["evaluated_at"], result["views"], shorts, search, result["average_view_duration"], result["average_view_percentage"], result["likes"], result["comments"], result["shares"], result["subscribers_gained"], video_id))
        conn.commit()
    return result
