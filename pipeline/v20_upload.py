"""V20 upload metadata: entertainment, minimal metadata, no custom thumbnail call."""
from __future__ import annotations

from typing import Any


def create_v20_upload_body(spec: dict[str, Any]) -> dict[str, Any]:
    title = str(spec["title"]).strip()[:90]
    tag = str(spec.get("tracking_tag", "")).strip()
    description = "#shorts" + (f"\n\n---\nRef: {tag}" if tag else "")
    return {
        "snippet": {
            "title": f"{title} #shorts",
            "description": description[:4900],
            "tags": ["shorts"],
            "categoryId": "24",
        },
        "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False},
    }
