"""End-to-end GitHub Actions YouTube Shorts pipeline.

Round 1 optimizations:
  #1  Thumbnail auto-extracted and uploaded
  #2  Hook image (scene 0) forced to striking single-subject visual (in script_gen)
  #3  SEO title optimized via second Gemini call (in script_gen)
  #4  Trending topics via Google Trends (pytrends) with static fallback
  #5  Pinned comment with per-scene timestamps after upload
  #6  Background music from assets/music/ (render.py)
  #7  Dynamic subtitle font size (render.py)
  #8  Scene count guardrail 3-8 (quality.py)
  #9  Upload cron scheduled for 7 AM IST, loops 20 videos every 45 min
  #10 Quota state tracks last successful topic for retry

Round 2 optimizations — anti-monotone variety pass:
  #1  Accent color per niche/category, threaded into render.py via `category=niche`
  #2  Caption box style rotates bar/pill/card per scene (render.py)
  #3  Subtitle + keyword text fades in instead of popping in (render.py)
  #4  Crossfade transition type rotates per cut (render.py)
  #5  Background music track picked per-video by hash of the slug, not always
      the alphabetically-first track (render.py)
  #6  Whoosh SFX layered under every scene cut (render.py + assets/sfx/)
  #7  Hook style (question/shocking-fact/numbered) rotates per topic (script_gen.py)
  #8  Prompt now asks for varied scene pacing instead of uniform length (script_gen.py)
  #9  Rotating outro CTA card appended as a final "scene" (render.py)
  #10 Thumbnail is now the best of 4 scored candidate frames from scene 0,
      not always a fixed 0.5s grab (render.py)
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from .config import Settings, YouTubeCredentials, CONTENT_PLAN_PATH, WORK_DIR, OUT_DIR, ensure_dirs
from .render import assemble_video
from .script_gen import generate_script
from .trending import get_trending_topic
from .tts import synthesize_scene
from .upload import upload_video
from .visuals import fetch_scene_image

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / ".quota_state.json"

# Gap between consecutive uploads (seconds). 45 min = 2700 s.
UPLOAD_INTERVAL_SECONDS: int = 45 * 60


def _truthy(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _csv_env(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name)
    if not raw:
        return default
    return [x.strip() for x in raw.split(",") if x.strip()]


def _decode_credential(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    if not raw:
        raise ValueError("empty credential")
    try:
        return json.loads(base64.b64decode(raw).decode("utf-8"))
    except Exception:
        return json.loads(raw)


def _load_settings() -> Settings:
    creds: list[YouTubeCredentials] = []
    for i in range(1, 20):
        raw = os.getenv(f"YT_CREDS_{i}")
        if not raw:
            continue
        try:
            creds.append(YouTubeCredentials(i, _decode_credential(raw)))
        except Exception as exc:
            print(f"[!] Ignoring invalid YT_CREDS_{i}: {exc}")

    return Settings(
        gemini_api_key=os.getenv("GEMINI_API_KEY"),
        openrouter_api_key=None,   # intentionally removed
        pexels_api_key=os.getenv("PEXELS_API_KEY"),
        pixabay_api_key=os.getenv("PIXABAY_API_KEY"),
        youtube_projects=creds,
        upload_enabled=_truthy(os.getenv("UPLOAD_ENABLED"), True),
        niches_enabled=_csv_env("NICHES_ENABLED", ["facts"]),
        languages_enabled=_csv_env("LANGUAGES_ENABLED", ["en"]),
    )


def _load_plan() -> dict[str, Any]:
    if not CONTENT_PLAN_PATH.exists():
        raise FileNotFoundError(f"Missing content plan: {CONTENT_PLAN_PATH}")
    data = json.loads(CONTENT_PLAN_PATH.read_text(encoding="utf-8"))
    return data.get("niches", data)


def _load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"niche": 0, "language": 0, "topic": 0, "project": 0,
                "last_successful_topic": None, "last_failed_topic": None}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return {
            "niche": int(data.get("niche", 0)),
            "language": int(data.get("language", 0)),
            "topic": int(data.get("topic", 0)),
            "project": int(data.get("project", 0)),
            "last_successful_topic": data.get("last_successful_topic"),
            "last_failed_topic": data.get("last_failed_topic"),
        }
    except Exception:
        return {"niche": 0, "language": 0, "topic": 0, "project": 0,
                "last_successful_topic": None, "last_failed_topic": None}


def _save_state(state: dict[str, Any]) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def _slug(text: str, max_len: int = 60) -> str:
    s = re.sub(r"[^\w\s-]", "", text.lower())
    s = re.sub(r"[\s_-]+", "-", s).strip("-")
    return s[:max_len] or "youtube-short"


def _choose(plan: dict[str, Any], settings: Settings, state: dict[str, Any]):
    available_niches = [
        n for n in settings.niches_enabled
        if n in plan and plan[n].get("topics")
    ]
    if not available_niches:
        raise RuntimeError(
            f"No enabled niches have topics. Enabled={settings.niches_enabled}; "
            f"available={list(plan)}"
        )

    niche = available_niches[state["niche"] % len(available_niches)]
    cfg = plan[niche]

    languages = [
        lang for lang in settings.languages_enabled
        if lang in cfg.get("voice", {})
    ]
    if not languages:
        raise RuntimeError(
            f"No enabled languages available for niche '{niche}'. "
            f"Enabled={settings.languages_enabled}; voices={list(cfg.get('voice', {}))}"
        )

    language = languages[state["language"] % len(languages)]
    topics = cfg["topics"]
    static_topic = topics[state["topic"] % len(topics)]

    # Optimization #4: try Google Trends first, fall back to static topic
    topic = get_trending_topic(niche, static_topic)

    # Optimization #10: if last run failed on a topic, retry it first
    if state.get("last_failed_topic") and state["last_failed_topic"] != state.get("last_successful_topic"):
        retry = state["last_failed_topic"]
        print(f"[pipeline] retrying previously failed topic: {retry!r}")
        topic = retry
        state["last_failed_topic"] = None
    else:
        state["niche"] += 1
        state["language"] += 1
        state["topic"] += 1

    return niche, cfg, language, topic


def _run_one(
    plan: dict[str, Any],
    settings: Settings,
    state: dict[str, Any],
    dry_run: bool,
    video_index: int,
) -> bool:
    """Generate, render, and upload one video. Returns True on success."""

    niche, niche_cfg, language, topic = _choose(plan, settings, state)
    print(f"\n[pipeline] ── video {video_index} ── niche={niche} language={language} topic={topic}")

    # Mark topic as in-progress so a crash is retryable
    state["last_failed_topic"] = topic
    _save_state(state)

    script = generate_script(topic, niche_cfg, language, settings, niche_key=niche)
    print(f"[pipeline] title={script.title!r}; scenes={len(script.scenes)}")

    voice = niche_cfg.get("voice", {}).get(language, "en-IN")
    visual_style = niche_cfg.get("visual_style", "handwritten_notes")

    # Use a per-video scene dir so parallel-ish reruns don't clobber each other
    scene_dir = WORK_DIR / f"scenes_{video_index:02d}"
    scene_dir.mkdir(parents=True, exist_ok=True)

    scene_images: list[Path] = []
    scene_audios: list[Path] = []
    scene_ass: list[Path] = []
    durations: list[float] = []
    scene_texts: list[str] = []
    scene_narrations: list[str] = []

    for scene in script.scenes:
        scene_no = scene.index + 1
        print(f"[pipeline] scene {scene_no}/{len(script.scenes)}")

        narration = (scene.narration or "").strip()
        tts_text = (scene.tts_text or narration).strip()
        if not narration:
            raise ValueError(f"Scene {scene_no} has empty narration after script normalization")
        if not tts_text:
            tts_text = narration

        audio_path = scene_dir / f"scene_{scene.index:02d}.mp3"
        ass_path   = scene_dir / f"scene_{scene.index:02d}.ass"

        audio, ass, duration = synthesize_scene(
            subtitle_text=narration,
            tts_text=tts_text,
            voice=voice,
            audio_path=audio_path,
            ass_path=ass_path,
            overlay_text=None,
        )

        image = fetch_scene_image(scene.index, scene.image_prompt, visual_style, settings)
        scene_images.append(image)
        scene_audios.append(audio)
        scene_ass.append(ass)
        durations.append(duration)
        scene_texts.append(scene.on_screen_text or "")
        scene_narrations.append(narration)

    # Write script metadata (overwritten each video — latest always wins)
    metadata_path = OUT_DIR / "script.json"
    metadata_path.write_text(json.dumps(script.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    video_path = assemble_video(
        scene_images,
        scene_audios,
        scene_ass,
        durations,
        _slug(script.title),
        scene_texts=scene_texts,
        scene_narrations=scene_narrations,
        category=niche,
    )
    print(f"[pipeline] rendered={video_path} size={video_path.stat().st_size / 1024 / 1024:.1f} MB")

    # Clean up per-video scene dir to keep disk usage flat across 20 videos
    shutil.rmtree(scene_dir, ignore_errors=True)

    # Mark topic as successfully rendered
    state["last_successful_topic"] = topic
    state["last_failed_topic"] = None

    if dry_run:
        print("[i] Dry run — skipping upload.")
        _save_state(state)
        return True

    if not settings.upload_enabled:
        print("[i] UPLOAD_ENABLED is disabled — skipping upload.")
        _save_state(state)
        return True

    if not settings.youtube_projects:
        raise RuntimeError("Upload requested but no YT_CREDS_N secrets are configured.")

    start = state["project"] % len(settings.youtube_projects)
    last_error: Exception | None = None

    for offset in range(len(settings.youtube_projects)):
        idx = (start + offset) % len(settings.youtube_projects)
        cred = settings.youtube_projects[idx]
        try:
            result = upload_video(
                video_path,
                script,
                [cred],
                scene_durations=durations,
            )
            state["project"] = idx + 1
            _save_state(state)
            print(f"[✓] Uploaded with YT_CREDS_{cred.index}: {result['url']}")
            return True
        except Exception as exc:
            last_error = exc
            print(f"[!] YT_CREDS_{cred.index} failed: {exc}")

    raise RuntimeError(f"All YouTube credentials failed: {last_error}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="render videos but never upload")
    parser.add_argument("--count", type=int, default=int(os.getenv("UPLOAD_COUNT", "15")),
                        help="number of videos to generate and upload (default: 15)")
    parser.add_argument("--interval", type=int, default=UPLOAD_INTERVAL_SECONDS,
                        help="seconds between uploads (default: 2700 = 45 min)")
    args = parser.parse_args()

    ensure_dirs()
    settings = _load_settings()
    plan = _load_plan()
    state = _load_state()

    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is required")

    total = args.count
    interval = args.interval
    succeeded = 0
    failed = 0

    print(f"[scheduler] Starting: {total} videos, {interval // 60} min apart")

    for i in range(1, total + 1):
        t_start = time.monotonic()
        print(f"\n[scheduler] ── [{i}/{total}] starting at {time.strftime('%H:%M:%S')} IST ──")

        try:
            _run_one(plan, settings, state, dry_run=args.dry_run, video_index=i)
            succeeded += 1
        except Exception as exc:
            failed += 1
            print(f"[!] Video {i} failed: {exc}")
            # Save state so the next video picks up where rotation left off
            _save_state(state)

        if i < total:
            elapsed = time.monotonic() - t_start
            sleep_for = max(0.0, interval - elapsed)
            print(f"[scheduler] video {i} done in {elapsed:.0f}s — "
                  f"sleeping {sleep_for / 60:.1f} min until next upload")
            time.sleep(sleep_for)

    print(f"\n[scheduler] Done — {succeeded} succeeded, {failed} failed out of {total}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
