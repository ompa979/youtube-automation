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

Round 2 optimizations — legacy notes retained for compatibility. Current V7 uses value-first teaching and premium hero thumbnails:
  #1  Accent color per niche/category, threaded into render.py via `category=niche`
  #2  Caption box style rotates bar/pill/card per scene (render.py)
  #3  Subtitle + keyword text fades in instead of popping in (render.py)
  #4  Crossfade transition type rotates per cut (render.py)
  #5  Background music track picked per-video by hash of the slug, not always
      the alphabetically-first track (render.py)
  #6  Whoosh SFX layered under every scene cut (render.py + assets/sfx/)
  #7  Hook style rotates between misconception/consequence/curiosity (script_gen.py)
  #8  Prompt now asks for varied scene pacing instead of uniform length (script_gen.py)
  #9  No generic outro CTA card; CTA stays outside the spoken teaching arc
  #10 Dedicated 9:16 Shorts premium AI-art thumbnails are generated independently of scene frames
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from .config import Settings, YouTubeCredentials, CONTENT_PLAN_PATH, WORK_DIR, OUT_DIR, ensure_dirs
from .render import assemble_video
from .script_gen import generate_script, ScriptRejected
from .subject_area import classify_subject_area
from .trending import get_trending_topic
from .topic_engine import ALLOWED_EXAM_NICHES, EXAM_ONLY, choose_best_topic
from .tts import synthesize_scene
from .upload import upload_video
from .v20_topic_engine import generate_v20_spec
from .v20_renderer import render_v20_short
from .v20_upload import create_v20_upload_body
from .v20_telemetry import record_v20_upload
from .visuals import fetch_scene_image
from .creative_v17 import apply_v17_creative_contract

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
    content_mode = os.getenv("CONTENT_MODE", "exam").strip().lower() or "exam"
    # Keep one shared secret namespace, but select the channel pool explicitly.
    # By default normal/exam content uses YT_CREDS_1 and viral content uses YT_CREDS_2.
    # Set YOUTUBE_CREDENTIAL_INDICES="1,2,3" to opt into an explicit fallback pool.
    credential_prefix = os.getenv("YOUTUBE_CREDENTIAL_PREFIX", "YT_CREDS").strip() or "YT_CREDS"
    default_index = "2" if content_mode == "viral" else "1"
    indices_raw = os.getenv("YOUTUBE_CREDENTIAL_INDICES", default_index).strip() or default_index
    try:
        indices = [int(x.strip()) for x in indices_raw.split(",") if x.strip()]
    except ValueError as exc:
        raise ValueError(f"Invalid YOUTUBE_CREDENTIAL_INDICES={indices_raw!r}; use comma-separated integers") from exc
    invalid = [i for i in indices if i < 1 or i > 19]
    if invalid:
        raise ValueError(f"YOUTUBE_CREDENTIAL_INDICES contains invalid values: {invalid}")

    creds: list[YouTubeCredentials] = []
    for i in indices:
        raw = os.getenv(f"{credential_prefix}_{i}")
        if not raw:
            continue
        try:
            creds.append(YouTubeCredentials(i, _decode_credential(raw)))
        except Exception as exc:
            print(f"[!] Ignoring invalid {credential_prefix}_{i}: {exc}")

    return Settings(
        gemini_api_key=os.getenv("GEMINI_API_KEY"),
        cloudflare_account_id=os.getenv("CLOUDFLARE_ACCOUNT_ID"),
        cloudflare_api_token=os.getenv("CLOUDFLARE_API_TOKEN"),
        openrouter_api_key=None,   # intentionally removed
        pexels_api_key=os.getenv("PEXELS_API_KEY"),
        pixabay_api_key=os.getenv("PIXABAY_API_KEY"),
        pollinations_api_key=os.getenv("POLLINATIONS_API_KEY") or os.getenv("POLLINATION_KEY"),
        youtube_projects=creds,
        upload_enabled=(
            _truthy(os.getenv("UPLOAD_ENABLED"), True)
            and not _truthy(os.getenv("DRY_RUN"), False)
        ),
        content_mode=content_mode,
        niches_enabled=_csv_env("NICHES_ENABLED", sorted(ALLOWED_EXAM_NICHES) if content_mode != "viral" else [
            "psychology_human_behavior", "money_personal_finance", "ai_future_tech", "career_work",
            "motivation_discipline", "science_everyday", "history_stories", "social_behaviour"
        ]),
        languages_enabled=_csv_env("LANGUAGES_ENABLED", ["en"]),
    )


def _load_plan() -> dict[str, Any]:
    content_mode = os.getenv("CONTENT_MODE", "exam").strip().lower() or "exam"
    plan_path = (ROOT / "viral_content_plan.json") if content_mode == "viral" else CONTENT_PLAN_PATH
    if not plan_path.exists():
        raise FileNotFoundError(f"Missing content plan: {plan_path}")
    data = json.loads(plan_path.read_text(encoding="utf-8"))
    return data.get("niches", data)


def _load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"niche": 0, "language": 0, "topic": 0, "project": 0,
                "last_successful_topic": None, "last_failed_topic": None,
                "last_niche": None, "recent_topics": [], "completed_topics": [], "topic_cursors": {}}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return {
            "niche": int(data.get("niche", 0)),
            "language": int(data.get("language", 0)),
            "topic": int(data.get("topic", 0)),
            "project": int(data.get("project", 0)),
            "last_successful_topic": data.get("last_successful_topic"),
            "last_failed_topic": data.get("last_failed_topic"),
            "last_niche": data.get("last_niche"),
            "recent_topics": list(data.get("recent_topics") or [])[-12:],
            "completed_topics": list(data.get("completed_topics") or []),
            "topic_cursors": dict(data.get("topic_cursors") or {}),
        }
    except Exception:
        return {"niche": 0, "language": 0, "topic": 0, "project": 0,
                "last_successful_topic": None, "last_failed_topic": None,
                "last_niche": None, "recent_topics": [], "completed_topics": [], "topic_cursors": {}}


def _save_state(state: dict[str, Any]) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def _slug(text: str, max_len: int = 60) -> str:
    s = re.sub(r"[^\w\s-]", "", text.lower())
    s = re.sub(r"[\s_-]+", "-", s).strip("-")
    return s[:max_len] or "youtube-short"


def _choose(plan: dict[str, Any], settings: Settings, state: dict[str, Any]):
    available_niches=[n for n in settings.niches_enabled if n in plan and plan[n].get("topics")]
    if settings.content_mode == "viral":
        # Viral mode is deliberately independent from the exam lane.
        os.environ["EXAM_ONLY"] = "false"
        os.environ["VIRAL_CONTENT_ONLY"] = "true"
    if EXAM_ONLY and settings.content_mode != "viral":
        filtered=[n for n in available_niches if n in ALLOWED_EXAM_NICHES]
        if filtered:
            available_niches=filtered
        else:
            available_niches=[n for n in sorted(ALLOWED_EXAM_NICHES) if n in plan and plan[n].get("topics")]
            print(f"[topic-v8] EXAM_ONLY=true: ignoring non-exam NICHES_ENABLED={settings.niches_enabled}; using {available_niches}")
    if not available_niches:
        raise RuntimeError(f"No enabled niches have topics. Enabled={settings.niches_enabled}; available={list(plan)}")
    try:
        niche,cfg,language,topic,score,board=choose_best_topic(plan,available_niches,state)
        state["last_niche"]=niche
        fit_label = "BROAD FIT" if settings.content_mode == "viral" else "EXAM FIT"
        print(f"[topic-v8] 🔥 TREND SCORE={score.trend_score:.0f}/100 | 🔎 SEO SCORE={score.seo_score:.0f}/100 | 🎯 {fit_label}={score.exam_fit:.0f}/100 | 💡 VALUE={score.value_density:.0f}/100 | 🎨 VISUAL={score.visual:.0f}/100 | 🚀 VIRAL={score.viral_fit:.0f}/100")
        print(f"[topic-v8] DISCOVERY ORDER: BROAD APPEAL → CURIOSITY → VISUAL → TREND → SEO" if settings.content_mode == "viral" else "[topic-v8] DISCOVERY ORDER: TREND → SEO → EXAM FIT → VALUE → VISUAL")
        print(f"[topic-v8] selected={topic!r} niche={niche} total={score.total:.1f}")
        for item in board[:5]: print(f"[topic-v8]  trend={item.trend_score:.0f} seo={item.seo_score:.0f} exam={item.exam_fit:.0f} value={item.value_density:.0f} visual={item.visual:.0f} | {item.topic}")
        return niche,cfg,language,topic
    except Exception as exc:
        print(f"[topic-v8] evidence selector unavailable, deterministic fallback: {exc}")
    rotation=[n for n in available_niches for _ in range(max(1,int(plan[n].get("weight",1))))]
    niche=rotation[state.get("niche",0)%len(rotation)]; cfg=plan[niche]
    language=next((lang for lang in settings.languages_enabled if lang in cfg.get("voice",{})),"en")
    topics=cfg["topics"]; topic=get_trending_topic(niche,topics[state.get("topic",0)%len(topics)])
    state["niche"]=state.get("niche",0)+1; state["language"]=state.get("language",0)+1; state["topic"]=state.get("topic",0)+1
    return niche,cfg,language,topic



def _run_v20_one(settings: Settings, state: dict[str, Any], dry_run: bool, video_index: int) -> bool:
    """Run one V20 feed-native video without script generation or TTS."""
    spec = generate_v20_spec(video_index)
    print(f"\n[v20] ── seed {video_index}/40 ── {spec['tracking_tag']} | {spec['format']} | {spec['subtype']}")
    print(f"[v20] hook={spec['hook_text']!r} duration={spec['duration_seconds']}s | evaluation=72h | thumbnail=FRAME_0")

    scene_dir = WORK_DIR / f"v20_{video_index:03d}"
    scene_dir.mkdir(parents=True, exist_ok=True)
    visual_paths: list[Path] = []
    # Generate several distinct visual states from the same concept.  The first
    # visual is intentionally the strongest frame and receives the hook overlay at t=0.
    prompts = [spec["visual_prompt"]]
    for i, detail in enumerate(spec.get("visual_parts", [])[:3], start=1):
        prompts.append(f"{spec['visual_prompt']}; emphasize {detail}; same scene, same subject, vertical 9:16")
    try:
        for idx, prompt in enumerate(prompts):
            # fetch_scene_image writes its own deterministic scene file; copy it into
            # the V20 run directory so multiple variants cannot overwrite each other.
            image = fetch_scene_image(
                1000 + video_index * 10 + idx,
                prompt,
                "ai_cinematic",
                settings,
                subject_area="science",
                card_headline="",
                card_points=[],
                card_tag="",
            )
            target = scene_dir / f"visual_{idx:02d}.jpg"
            shutil.copy2(image, target)
            visual_paths.append(target)
            print(f"[v20] visual {idx + 1}/{len(prompts)} ready: {target.name}")

        output = OUT_DIR / f"v20_{video_index:03d}_{_slug(spec['subtype'])}.mp4"
        render_v20_short(visual_paths, spec, output)
        print(f"[v20] rendered={output} size={output.stat().st_size / 1024 / 1024:.1f} MB")

        # A lightweight Script-shaped object is used only for the existing uploader's
        # public interface; it contains no narration and no TTS metadata.
        from .script_gen import Script
        script = Script(
            title=spec["title"],
            hook=spec["hook_text"],
            description=spec["description"],
            tags=spec["tags"],
            scenes=[],
            pinned_comment="",
            content_mode="v20",
        )
        if dry_run or not settings.upload_enabled:
            print("[v20] dry-run/upload-disabled: YouTube mutation skipped")
            return True
        if not settings.youtube_projects:
            raise RuntimeError("V20 upload requested but no YT_CREDS_N secrets are configured")

        result = upload_video(
            output,
            script,
            settings.youtube_projects,
            category_id="24",
            scene_durations=None,
            v20_spec=spec,
        )
        record_v20_upload(result["video_id"], spec)
        print(f"[v20] uploaded={result['url']} | thumbnail=SKIPPED_NATIVE_FRAME_0")
        state.setdefault("v20_completed", []).append(spec["tracking_tag"])
        state["v20_index"] = video_index
        if not dry_run:
            _save_state(state)
        return True
    finally:
        shutil.rmtree(scene_dir, ignore_errors=True)


def _run_one(
    plan: dict[str, Any],
    settings: Settings,
    state: dict[str, Any],
    dry_run: bool,
    video_index: int,
) -> bool:
    """Generate, render, and upload one video. Returns True on success."""

    if settings.content_mode == "v20":
        return _run_v20_one(settings, state, dry_run, video_index)

    niche, niche_cfg, language, topic = _choose(plan, settings, state)
    print(f"\n[pipeline] ── video {video_index} ── niche={niche} language={language} topic={topic}")

    # Mark topic as in-progress so a live crash is retryable.
    # Dry runs are intentionally side-effect free and do not persist state.
    state["last_failed_topic"] = topic
    if not dry_run:
        _save_state(state)

    script = None
    topics = niche_cfg.get("topics", [topic])
    current_topic = topic
    for attempt in range(3):
        try:
            script = generate_script(current_topic, niche_cfg, language, settings, niche_key=niche)
            script.content_mode = settings.content_mode
            topic = current_topic
            break
        except ScriptRejected as exc:
            print(f"[pipeline] topic REJECTED: {current_topic!r} — {exc}")
            state["last_failed_topic"] = None
            if attempt < 2:
                state["topic"] += 1
                current_topic = topics[state["topic"] % len(topics)]
                print(f"[pipeline] Trying next candidate topic in queue: {current_topic!r}")
            else:
                if not dry_run:
                    _save_state(state)
                raise

    # V17 creative director: deterministic post-processing, no extra Gemini call.
    v17 = apply_v17_creative_contract(script, topic, niche_cfg)
    print(f"[creative-v17] family={v17.visual_family!r} hero={v17.hero_headline!r} subline={v17.hero_subline!r}")
    print(f"[pipeline] title={script.title!r}; scenes={len(script.scenes)}; creative={getattr(script, 'creative_version', 'v17')}")

    voice = niche_cfg.get("voice", {}).get(language, "en-IN")
    visual_style = niche_cfg.get("visual_style", "handwritten_notes")
    subject_area = classify_subject_area(topic)
    print(f"[pipeline] subject_area={subject_area}")

    # Use a per-video scene dir so parallel-ish reruns don't clobber each other
    scene_dir = WORK_DIR / f"scenes_{video_index:02d}"
    scene_dir.mkdir(parents=True, exist_ok=True)

    # Per-scene TTS + image fetch used to run fully sequential (one scene's
    # audio, then its image, then the next scene's audio, ...). Both calls
    # are pure network I/O (edge-tts/gTTS, Cloudflare Workers AI and Pexels), so they
    # were mostly just blocking on the wire rather than on CPU. Running scenes
    # concurrently is the single biggest lever on total build time — for a
    # typical 6-scene video this turns roughly 6x(TTS + image) of sequential
    # wall time into ~ceil(6/SCENE_WORKERS)x, a multi-minute cut per video.
    # Workers are capped to avoid rate-limit bursts against the free image endpoints.
    # edge-tts endpoints rather than firing every scene at once.
    default_workers = "2" if os.getenv("IMAGE_PROVIDER", "cloudflare").strip().lower() == "cloudflare" else "4"
    scene_workers = max(1, int(os.getenv("SCENE_WORKERS", default_workers)))

    def _process_scene(scene) -> dict:
        scene_no = scene.index + 1
        narration = (scene.narration or "").strip()
        tts_text = (scene.tts_text or narration).strip()
        if not narration:
            raise ValueError(f"Scene {scene_no} has empty narration after script normalization")
        if not tts_text:
            tts_text = narration

        audio_path = scene_dir / f"scene_{scene.index:02d}.mp3"
        ass_path   = scene_dir / f"scene_{scene.index:02d}.ass"

        audio, word_timings, duration = synthesize_scene(
            subtitle_text=narration,
            tts_text=tts_text,
            voice=voice,
            audio_path=audio_path,
            ass_path=ass_path,
            overlay_text=None,
        )
        image = fetch_scene_image(
            scene.index, scene.image_prompt, visual_style, settings, subject_area=subject_area,
            card_headline=(script.title if scene.index == 0 else (scene.on_screen_text or "")),
            card_points=scene.card_points,
            card_tag=niche_cfg.get("card_tag", ""),
        )
        return {
            "index": scene.index,
            "image": image,
            "audio": audio,
            "ass": ass_path,
            "duration": duration,
            "text": scene.on_screen_text or "",
            "narration": narration,
            "word_timings": word_timings or [],
            "card_points": scene.card_points or [],
            "visual_mode": getattr(scene, "visual_mode", "concept"),
        }

    print(f"[pipeline] processing {len(script.scenes)} scenes with {scene_workers} parallel workers")
    results: dict[int, dict] = {}
    with ThreadPoolExecutor(max_workers=min(scene_workers, len(script.scenes))) as pool:
        futures = {pool.submit(_process_scene, scene): scene.index for scene in script.scenes}
        for future in as_completed(futures):
            idx = futures[future]
            results[idx] = future.result()  # raises immediately if a scene failed
            print(f"[pipeline] scene {idx + 1}/{len(script.scenes)} ready")

    ordered = [results[scene.index] for scene in script.scenes]
    scene_images: list[Path] = [r["image"] for r in ordered]
    scene_audios: list[Path] = [r["audio"] for r in ordered]
    scene_ass: list[Path] = [r["ass"] for r in ordered]
    durations: list[float] = [r["duration"] for r in ordered]
    scene_texts: list[str] = [r["text"] for r in ordered]
    scene_narrations: list[str] = [r["narration"] for r in ordered]
    scene_word_timings: list[list[dict]] = [r["word_timings"] for r in ordered]
    scene_card_points: list[list[str]] = [r["card_points"] for r in ordered]
    scene_visual_modes: list[str] = [r.get("visual_mode", "concept") for r in ordered]
    scene_action_types: list[str] = [getattr(scene, "action_type", "explanation") for scene in script.scenes]
    scene_action_payloads: list[str] = [getattr(scene, "action_payload", "") for scene in script.scenes]
    scene_motion_types: list[str] = [getattr(scene, "motion_type", "") for scene in script.scenes]
    scene_camera_motions: list[str] = [getattr(scene, "camera_motion", "") for scene in script.scenes]
    scene_sfx_cues: list[str] = [getattr(scene, "sfx_cue", "") for scene in script.scenes]

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
        topic=topic,
        scene_word_timings=scene_word_timings,
        scene_card_points=scene_card_points,
        scene_visual_modes=scene_visual_modes,
        scene_action_types=scene_action_types,
        scene_action_payloads=scene_action_payloads,
        scene_motion_types=scene_motion_types,
        scene_camera_motions=scene_camera_motions,
        scene_sfx_cues=scene_sfx_cues,
        thumbnail_text=getattr(script, "thumbnail_text", ""),
        thumbnail_label=(niche_cfg.get("card_tag", "") or (script.title.split("|")[-1].strip() if "|" in script.title else niche.replace("_", " "))),
        thumbnail_subline=getattr(script, "thumbnail_subline", ""),
        thumbnail_visual_prompt=getattr(script, "thumbnail_visual_prompt", ""),
        creative_headline=getattr(script, "hero_headline", ""),
        creative_subline=getattr(script, "hero_subline", ""),
        creative_badge=getattr(script, "creative_badge", ""),
    )
    print(f"[pipeline] rendered={video_path} size={video_path.stat().st_size / 1024 / 1024:.1f} MB")

    # Clean up per-video scene dir to keep disk usage flat across 20 videos
    shutil.rmtree(scene_dir, ignore_errors=True)

    # Mark topic as successfully rendered
    state["last_successful_topic"] = topic
    state["last_failed_topic"] = None

    if dry_run:
        print("[dry-run] Render complete — upload and YouTube mutations skipped.")
        print(f"[dry-run] Video: {video_path}")
        print(f"[dry-run] Thumbnail: {OUT_DIR / 'thumbnail.jpg'}")
        return True

    if not settings.upload_enabled:
        print("[i] UPLOAD_ENABLED is disabled — skipping upload.")
        _save_state(state)
        return True

    if not settings.youtube_projects:
        raise RuntimeError("Upload requested but no YT_CREDS_N secrets are configured.")

    start = state["project"] % len(settings.youtube_projects)
    ordered_projects = (
        settings.youtube_projects[start:] + settings.youtube_projects[:start]
    )
    try:
        result = upload_video(
            video_path,
            script,
            ordered_projects,
            scene_durations=durations,
        )
        used_name = result["project"]
        used_idx = next((i for i, cred in enumerate(settings.youtube_projects) if cred.name == used_name), start)
        state["project"] = (used_idx + 1) % len(settings.youtube_projects)
        state.setdefault("completed_topics", []).append(topic)
        state["recent_topics"] = (state.get("recent_topics", []) + [topic])[-12:]
        _save_state(state)
        print(f"[✓] Uploaded with {used_name}: {result['url']}")
        try:
            from .seo import TopicMemory
            tm = TopicMemory()
            meta = getattr(script, "seo_metadata", {}) or {}
            tm.record_completed_video(
                topic=topic,
                youtube_id=result.get("id", result.get("video_id", result.get("url", ""))),
                seo_score=meta.get("seo_score", 0),
                retention_score=meta.get("retention_score", 0),
            )
        except Exception as exc:
            print(f"[!] TopicMemory recording failed (non-fatal): {exc}")
        return True
    except Exception as exc:
        raise RuntimeError(f"All YouTube credentials failed: {exc}") from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="render videos and thumbnails but never upload or mutate YouTube")
    default_count = 40 if os.getenv("CONTENT_MODE", "exam").strip().lower() == "v20" else int(os.getenv("UPLOAD_COUNT", "3"))
    parser.add_argument("--count", type=int, default=default_count,
                        help="number of videos to generate and upload (V20 default: 40)")
    parser.add_argument("--interval", type=int, default=UPLOAD_INTERVAL_SECONDS,
                        help="seconds between uploads (default: 2700 = 45 min)")
    args = parser.parse_args()

    ensure_dirs()
    settings = _load_settings()
    plan = _load_plan()
    state = _load_state()

    if settings.content_mode not in {"v20"} and not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is required")

    dry_run = args.dry_run or _truthy(os.getenv("DRY_RUN"), False)
    total = args.count
    interval = args.interval
    succeeded = 0
    failed = 0

    mode = "DRY RUN" if dry_run else "LIVE"
    print(f"[scheduler] Mode: {mode}")
    print(f"[scheduler] Starting: {total} videos, {interval // 60} min apart")

    v20_base_index = int(os.getenv("V20_SEED_INDEX", "1")) if settings.content_mode == "v20" else 1
    if settings.content_mode == "v20" and v20_base_index > 40:
        print(f"[v20] 40-video seed complete; ignoring scheduled slot {v20_base_index}.")
        return 0
    for i in range(1, total + 1):
        t_start = time.monotonic()
        print(f"\n[scheduler] ── [{i}/{total}] starting at {time.strftime('%H:%M:%S')} IST ──")

        try:
            run_index = v20_base_index + i - 1 if settings.content_mode == "v20" else i
            _run_one(plan, settings, state, dry_run=dry_run, video_index=run_index)
            succeeded += 1
        except Exception as exc:
            failed += 1
            print(f"[!] Video {i} failed: {exc}")
            # Save state for live runs so the next run picks up where rotation left off.
            # Dry runs are intentionally side-effect free.
            if not dry_run:
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
