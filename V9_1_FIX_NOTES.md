# V9.1 Fixes

- Fixed FFmpeg render crash in final `difference_card` scene caused by invalid `\\*` expression escaping in drawbox width expressions.
- Final comparison card now uses `iw`/`ih` constants for robust FFmpeg sizing.
- Removed stale V6 runtime override at the bottom of `pipeline/generate.py` so the V8 Trend -> SEO topic selector is actually used at runtime.
- Added `urllib3<2.0` compatibility pin for `pytrends==4.9.2` to prevent `Retry(method_whitelist=...)` failures on fresh GitHub runners.
- Verified 260/260 repository tests pass.
- Verified final comparison scene renders successfully to 1080x1920 MP4.
