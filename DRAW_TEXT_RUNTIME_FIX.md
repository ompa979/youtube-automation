# FFmpeg drawtext runtime fix

GitHub-hosted FFmpeg can expose `drawtext` differently across runner binaries. V13 detects filter availability at runtime and defaults motion-graphic text to OFF, using ASS captions plus drawbox-only graphics. Text HUDs can still be enabled explicitly when `drawtext` is available. This prevents `No such filter: drawtext` from aborting the whole render.
