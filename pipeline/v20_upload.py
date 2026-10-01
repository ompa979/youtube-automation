"""V20 upload metadata: entertainment, minimal metadata, no custom thumbnail call."""
from __future__ import annotations

from typing import Any


def create_v20_upload_body(spec: dict[str, Any]) -> dict[str, Any]:
    title = str(spec["title"]).strip()[:90]
    return {
        "snippet": {
            "title": f"{title} #shorts",
            "description": "#shorts",
            "tags": ["shorts"],
            "categoryId": "24",
        },
        "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False},
    }
