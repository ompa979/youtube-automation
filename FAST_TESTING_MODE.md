# Fast CI testing mode

The scheduled/default GitHub Actions path now runs only the focused thumbnail
regression smoke suite in `tests/test_fast_thumbnail_ci.py`.

Use **workflow_dispatch → test_mode=full** when you want the complete pytest
suite. Pip caching is enabled on the Python setup step to reduce dependency
installation time on subsequent runs.
