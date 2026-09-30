# V16 — Script Runtime + Trend Fallback Fix

## Fixed
- Raised the value-first V6 script hard cap from 85 to 100 words. The target is 65–85 words; 55 remains the minimum.
- Repair prompts now use the same 65–85 target and 100-word hard cap.
- Removed the unsupported Gemini response-schema path from active Script/Repair generation. JSON is still requested by prompt and validated/repaired after generation, eliminating repeated `response_schema rejected by SDK` noise.
- Google Trends outages/rate limits no longer become a fake fixed Trend=35 signal.
- When live Google Trends is unavailable, the topic engine logs a neutral 50/100 fallback and ranks by SEO → exam fit → value → visual instead of allowing synthetic trend data to dominate.
- Added regression tests for the 100-word ceiling and Trends outage behavior.

## Validation
- 279 tests passed
- Python compile check passed
