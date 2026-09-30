from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_generate_supports_cli_dry_run_and_environment_gate():
    src = (ROOT / "pipeline" / "generate.py").read_text(encoding="utf-8")
    assert 'parser.add_argument("--dry-run"' in src
    assert '_truthy(os.getenv("DRY_RUN"), False)' in src
    assert '[dry-run] Render complete — upload and YouTube mutations skipped.' in src


def test_workflow_exposes_safe_dry_run_and_skips_youtube_credentials_check():
    src = (ROOT / ".github" / "workflows" / "generate.yml").read_text(encoding="utf-8")
    assert 'dry_run:' in src
    assert '--dry-run' in src
    assert "if: env.DRY_RUN != 'true'" in src
    assert 'Upload dry-run artifacts' in src
