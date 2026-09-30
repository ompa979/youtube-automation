# CI pytest fix

The GitHub Actions runner failed with `No module named pytest` because pytest was not declared/installed in the fresh Python environment.

Fixes:
- `requirements.txt` now pins `pytest==8.4.2`.
- `.github/workflows/generate.yml` explicitly installs `pytest==8.4.2` before the sanity test.
- The sanity command remains `python -m pytest -q`.

Local pytest execution could not be performed in the packaging environment because outbound package downloads are unavailable here. The workflow YAML was parsed successfully.
