# Credential Routing Fix — YT_CREDS_1 Normal / YT_CREDS_2 Viral

The YouTube credential namespace is shared. Channel routing is explicit by content mode:

- `CONTENT_MODE=exam` → `YT_CREDS_1`
- `CONTENT_MODE=viral` → `YT_CREDS_2`

The GitHub Actions workflow sets `YOUTUBE_CREDENTIAL_INDICES` automatically from `content_mode`, so viral mode no longer looks for `VIRAL_YT_CREDS_*` secrets.

For an intentional fallback pool, set `YOUTUBE_CREDENTIAL_INDICES="2,3"` (or another explicit comma-separated list). The default remains isolated to one channel per mode so normal uploads cannot accidentally fall onto the viral channel, or vice versa.
