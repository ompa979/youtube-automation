"""SEO V3 — Topic Memory + Search Domination Series."""
from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path

SERIES_CLUSTERS: dict[str, list[str]] = {
    "dbms_series": [
        "BCNF vs 3NF in DBMS | IBPS SO IT",
        "1NF 2NF 3NF Normalization in DBMS | IBPS SO IT",
        "Functional Dependency in DBMS | IBPS SO IT",
        "ACID Properties in DBMS | IBPS SO IT",
        "SQL Joins: Inner Outer Left Right | IBPS SO IT",
        "SQL GROUP BY vs HAVING | IBPS SO IT",
        "SQL Correlated Subquery vs JOIN | IBPS SO IT",
        "Primary Key vs Candidate Key vs Foreign Key | IBPS SO IT",
        "Deadlock Detection Banker Algorithm | IBPS SO IT",
        "Transaction Isolation Levels | IBPS SO IT",
    ],
    "networking_series": [
        "TCP 3-Way Handshake SYN ACK | IBPS SO IT",
        "OSI Model 7 Layers | IBPS SO IT",
        "OSI Layer 3 vs Layer 4 | IBPS SO IT",
        "Subnetting Shortcut without Binary | IBPS SO IT",
        "IPv4 vs IPv6 Subnetting | IBPS SO IT",
        "RSA vs AES Encryption | IBPS SO IT",
    ],
    "banking_awareness_series": [
        "CRR vs SLR Difference | Bank Exams",
        "Repo Rate vs Reverse Repo Rate | Bank Exams",
        "SDF vs Reverse Repo Rate | SBI PO",
        "NEFT vs RTGS vs IMPS Settlement Time | Bank Exams",
        "NPA Classification 90-Day Rule | IBPS PO",
        "Basel III Capital Adequacy Ratio | Bank Exams",
        "PCA Framework 3 Trigger Points | IBPS PO",
        "Priority Sector Lending PSL 40% | IBPS PO",
    ],
    "rbi_economy_series": [
        "GDP vs GNP vs NNP | RBI Grade B",
        "Money Supply M1 M2 M3 M4 | RBI Grade B",
        "Fiscal Deficit vs Revenue Deficit | RBI Grade B",
        "Demand-Pull vs Cost-Push Inflation | RBI Grade B",
        "Current Account vs Capital Account | RBI Grade B",
        "Monetary Policy Transmission | RBI Grade B",
    ],
}

_MEMORY_FILE_NAME = "topic_memory.json"

@dataclass
class CompletedVideo:
    topic: str
    series_key: str
    series_index: int
    youtube_id: str
    published_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    seo_score: int = 0
    retention_score: int = 0

class TopicMemory:
    def __init__(self, memory_dir: str | Path = "."):
        self._path = Path(memory_dir) / _MEMORY_FILE_NAME
        self._completed: list[CompletedVideo] = []
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                self._completed = [CompletedVideo(**item) for item in raw.get("completed", [])]
            except Exception:
                self._completed = []

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {"completed": [asdict(v) for v in self._completed]}
        self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def record_completed_video(
        self,
        topic: str,
        youtube_id: str,
        seo_score: int = 0,
        retention_score: int = 0,
    ) -> None:
        series_key, series_index = self._find_series(topic)
        video = CompletedVideo(
            topic=topic,
            series_key=series_key,
            series_index=series_index,
            youtube_id=youtube_id,
            seo_score=seo_score,
            retention_score=retention_score,
        )
        self._completed.append(video)
        self._save()
        print(f"[topic_memory] recorded: {topic!r} -> series={series_key}, index={series_index}, yt={youtube_id}")

    def _find_series(self, topic: str) -> tuple[str, int]:
        topic_lower = topic.lower()
        for key, topics in SERIES_CLUSTERS.items():
            for idx, series_topic in enumerate(topics):
                if series_topic.lower() == topic_lower:
                    return key, idx
                series_words = set(series_topic.lower().split())
                topic_words = set(topic_lower.split())
                if len(series_words & topic_words) >= 3:
                    return key, idx
        return "ungrouped", -1

    def get_series_progress(self, series_key: str) -> dict:
        series_topics = SERIES_CLUSTERS.get(series_key, [])
        completed_topics = {v.topic.lower() for v in self._completed if v.series_key == series_key}
        return {
            "series_key": series_key,
            "total": len(series_topics),
            "completed": len(completed_topics),
            "remaining": [t for t in series_topics if t.lower() not in completed_topics],
        }

    def get_next_topic_for_series(self, series_key: str) -> str | None:
        progress = self.get_series_progress(series_key)
        remaining = progress.get("remaining", [])
        return remaining[0] if remaining else None

    def completed_count(self) -> int:
        return len(self._completed)
