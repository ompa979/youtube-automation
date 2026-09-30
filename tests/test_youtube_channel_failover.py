from pathlib import Path

from pipeline.config import YouTubeCredentials
from pipeline.upload import _ordered_projects


def test_workflow_exposes_nineteen_youtube_credentials():
    src = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "generate.yml").read_text(encoding="utf-8")
    for i in range(1, 20):
        assert f"YT_CREDS_{i}: ${{{{ secrets.YT_CREDS_{i} }}}}" in src
    assert "for i in $(seq 1 19); do" in src


def test_ordered_projects_starts_at_quota_eligible_project(monkeypatch, tmp_path):
    import pipeline.upload as upload

    monkeypatch.setattr(upload, "pick_project", lambda names: (names[1], object()))
    projects = [
        YouTubeCredentials(1, {}),
        YouTubeCredentials(2, {}),
        YouTubeCredentials(3, {}),
    ]
    ordered, _ = _ordered_projects(projects)
    assert [p.index for p in ordered] == [2, 3, 1]
