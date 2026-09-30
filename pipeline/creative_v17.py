"""V17 ExamCracker creative director.

Turns the value-first V8/V6 script contract into a compact information-design
system for Shorts:
  - AI artwork is the visual layer, not the text layer.
  - Every Short gets one visual family/hero concept.
  - Scene copy becomes topic-specific instead of subtitle fragments.
  - The first frame gets a real teaching headline and subject line.
  - Scene roles map to three visual modes: concept, worked_example, exam_card.

No model/network calls are made here; this is a deterministic post-processor.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


V17_VERSION = "v17_information_design"
GENERIC_LABELS = {
    "WHY THIS MATTERS", "THE CONTEXT", "HOW IT WORKS", "WORKED EXAMPLE",
    "EXAM CLUE", "KEY DIFFERENCE", "REMEMBER", "KEY CONCEPT", "THE CONCEPT",
    "THE MECHANISM", "THE RULE", "ONE EXAMPLE", "THE EXAMPLE", "THE ANSWER",
    "WHY THIS", "WHAT HAPPENS", "UNDERSTAND THIS",
}
ROLE_MODE = {
    "hook": "concept",
    "context": "concept",
    "mechanism": "concept",
    "example": "worked_example",
    "exam_takeaway": "exam_card",
    "difference_card": "exam_card",
    "pattern_interrupt": "concept",
    "tension": "concept",
    "transformation": "worked_example",
    "payoff": "exam_card",
    "loop": "concept",
}


def _clean(value: str) -> str:
    return " ".join(str(value or "").replace("\n", " ").split()).strip()


def _words(value: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9]+(?:[-/][A-Za-z0-9]+)*", _clean(value))


def _topic_core(topic: str) -> str:
    t = _clean(topic)
    head = t.split(":", 1)[0].strip()
    head = re.sub(r"\bfor\s+(?:the\s+)?(?:exam|exams)\b", "", head, flags=re.I)
    head = re.sub(r"\s+\|.*$", "", head)
    head = _clean(head)
    if len(_words(head)) <= 8:
        return head
    return " ".join(_words(head)[:8])


def _suffix(topic: str) -> str:
    low = topic.lower()
    mappings = [
        (r"\bcrr\b.*\bslr\b", "WHERE EACH RESERVE SITS"),
        (r"\bsdf\b.*\breverse repo\b", "WHICH WAY LIQUIDITY MOVES"),
        (r"npa.*90.?day", "THE 90-DAY RULE"),
        (r"m1.*m2.*m3|m1.*m3", "WHY M3 IS BROADER"),
        (r"tcp.*handshake", "WHAT SYN AND ACK DO"),
        (r"group by.*having", "WHICH ROWS GET FILTERED"),
        (r"correlated subquery.*join", "HOW THE QUERY LOGIC DIFFERS"),
        (r"deadlock.*coffman", "THE 4 CONDITIONS"),
        (r"banker algorithm", "HOW A SAFE STATE WORKS"),
        (r"bcnf.*3nf", "THE CANDIDATE-KEY TEST"),
        (r"rsa.*aes", "WHEN EACH ENCRYPTION TYPE FITS"),
        (r"ac[iı]d", "WHY ISOLATION CHANGES RESULTS"),
        (r"percentage change", "THE FASTEST SAFE METHOD"),
        (r"successive discount", "WHY DISCOUNTS DO NOT ADD"),
        (r"ratio and proportion", "SCALE THE MIXTURE"),
        (r"time.*work", "THE LCM METHOD"),
        (r"syllogism", "FOLLOW THE QUANTIFIER"),
        (r"blood relations", "BUILD THE FAMILY TREE"),
        (r"circular seating", "INSIDE VS OUTSIDE"),
        (r"subject-verb agreement", "THE SINGULAR-VERB CLUE"),
        (r"para jumbles", "FIND THE OPENING LINE"),
        (r"fiscal deficit.*revenue deficit", "WHERE INTEREST FITS"),
        (r"demand-pull.*cost-push", "WHAT AN OIL SHOCK CHANGES"),
        (r"monetary policy transmission", "HOW RATES REACH BORROWERS"),
    ]
    for pattern, value in mappings:
        if re.search(pattern, low):
            return value
    # Topic titles often contain the useful mechanism after the colon.
    if ":" in topic:
        tail = _clean(topic.split(":", 1)[1])
        tail = re.sub(r"\b(with|using|for|in one|conceptually)\b.*$", "", tail, flags=re.I)
        candidate = " ".join(_words(tail)[:6])
        if candidate:
            return candidate.upper()
    return "ONE CLEAR MECHANISM"


def _is_valid_headline(text: str) -> bool:
    s = _clean(text)
    if not s or s.upper() in GENERIC_LABELS:
        return False
    ws = _words(s)
    if not (2 <= len(ws) <= 7):
        return False
    if s.endswith(('.', ',', ':', ';')):
        return False
    # Subtitle fragments such as "requiring immediate" or "branch totals"
    # are intentionally rejected when they look like sentence continuations.
    if s.lower().startswith(("requiring ", "designed ", "pledge ", "branch ", "massive ", "the following ")):
        return False
    return True


def _safe_short(value: str, max_words: int = 8, max_chars: int = 82) -> str:
    s = _clean(value)
    ws = _words(s)
    if len(ws) > max_words:
        s = " ".join(ws[:max_words])
    return s[:max_chars].rstrip(" -:,;")


@dataclass
class V17Meta:
    hero_headline: str
    hero_subline: str
    visual_family: str


def _viral_suffix(topic: str) -> str:
    low = (topic or "").lower()
    mapping = [
        (r"unfinished|task", "WHY IT STICKS"),
        (r"negative|compliment", "WHY IT LINGERS"),
        (r"choice|decisions", "TOO MANY CHOICES"),
        (r"deadline", "WHY DEADLINES WORK"),
        (r"compound", "WHY IT ACCELERATES"),
        (r"lifestyle inflation|salary", "WHERE THE EXTRA GOES"),
        (r"ai|model|token|context", "THE HIDDEN MECHANISM"),
        (r"motivation|discipline|habit", "WHY SYSTEMS WIN"),
        (r"metal|wood|ice|sky|bubble|onion|popcorn|static", "THE SCIENCE BEHIND IT"),
        (r"printing|paper|silk road|roman|zero|calendar|map", "THE CHANGE IT CREATED"),
    ]
    for pattern, value in mapping:
        if re.search(pattern, low):
            return value
    if ":" in topic:
        tail = _clean(topic.split(":", 1)[1])
        return " ".join(_words(tail)[:6]).upper() or "THE HIDDEN MECHANISM"
    return "THE HIDDEN MECHANISM"


def apply_v17_creative_contract(script, topic: str, niche_cfg: dict | None = None) -> V17Meta:
    """Mutate a Script into the deterministic V17 information-design contract."""
    niche_cfg = niche_cfg or {}
    core = _topic_core(topic)
    if niche_cfg.get("content_mode") == "viral":
        suffix = _viral_suffix(topic)
        badge = _clean(niche_cfg.get("card_tag", "VIRAL SHORTS")).upper()
    else:
        suffix = _suffix(topic)
        badge = _clean(niche_cfg.get("card_tag", "EXAMCRACKER AI")).upper()

    # Strong first frame: a meaningful concept headline + a mechanism promise.
    hero_headline = _safe_short(core.upper(), max_words=7, max_chars=38)
    hero_subline = _safe_short(suffix.upper(), max_words=7, max_chars=42)
    if not hero_headline:
        hero_headline = "THE CONCEPT"
    if not hero_subline:
        hero_subline = "ONE CLEAR MECHANISM"

    scenes = list(getattr(script, "scenes", []) or [])
    for i, scene in enumerate(scenes[:6]):
        role = getattr(scene, "action_type", "") or ("hook" if i == 0 else "mechanism")
        role = role.lower().strip()
        mode = ROLE_MODE.get(role, "concept")
        scene.visual_mode = mode

        current = _safe_short(getattr(scene, "on_screen_text", ""), max_words=7, max_chars=60)
        if not _is_valid_headline(current):
            if niche_cfg.get("content_mode") == "viral":
                viral_defaults = {
                    "pattern_interrupt": hero_headline,
                    "tension": "HERE'S WHAT HAPPENS",
                    "mechanism": suffix,
                    "transformation": "WATCH IT CHANGE",
                    "payoff": "NOW IT MAKES SENSE",
                    "loop": "REMEMBER THIS",
                }
                current = viral_defaults.get(role, hero_headline)
            elif role == "hook":
                current = hero_headline
            elif role == "context":
                current = "WHAT CHANGES FIRST" if "vs" in topic.lower() else f"{core.upper()} — CORE PARTS"
            elif role == "mechanism":
                current = suffix
            elif role == "example":
                current = "ONE WORKED EXAMPLE"
            elif role == "exam_takeaway":
                current = "EXAM CLUE — SPOT THIS"
            elif role == "difference_card":
                current = "KEY DIFFERENCE"
            else:
                current = core.upper()
        scene.on_screen_text = _safe_short(current.upper(), max_words=7, max_chars=60)

        # The memory anchor is the structured information card, not a second caption.
        points = list(getattr(scene, "card_points", []) or [])
        anchor = _clean(points[0] if points else "")
        if not anchor:
            anchor = _clean(getattr(scene, "action_payload", ""))
        scene.card_points = [_safe_short(anchor.upper(), max_words=9, max_chars=68)] if anchor else []
        if getattr(scene, "action_payload", ""):
            scene.action_payload = _safe_short(scene.action_payload, max_words=12, max_chars=100)

        # Give the image generator one persistent visual family and a scene-specific event.
        raw_prompt = _clean(getattr(scene, "image_prompt", ""))
        continuity = (
            f"V17 VISUAL FAMILY: {core}. Keep the same hero subject/material language across the Short. "
            "This is the visual explanation layer, not a text slide. "
        )
        role_visual = {
            "hook": "single dominant hero subject, captured at the moment the key change becomes visible, high silhouette readability",
            "context": "clear two-part composition that distinguishes the essential elements without written labels",
            "mechanism": "physical cause-to-effect sequence or diagrammatic transformation; show what moves, changes, joins or splits",
            "example": "worked-example composition using one concrete object, transaction, packet, row, number set or other topic-appropriate artifact",
            "exam_takeaway": "clean exam-signal composition that visually isolates the condition, clue or rule that decides the answer",
            "difference_card": "split composition with two distinct conceptual sides and an obvious visual divider; comparison, not a quiz",
        }.get(role, "one clear physical transformation")
        scene.image_prompt = _safe_short(
            continuity + role_visual + ". " + raw_prompt,
            max_words=85,
            max_chars=900,
        )

    # Keep the script's searchable title but force thumbnail/header copy into the V17 design.
    script.hero_headline = hero_headline
    script.hero_subline = hero_subline
    script.creative_version = V17_VERSION
    script.creative_badge = badge or "EXAMCRACKER AI"
    script.visual_family = core
    if not getattr(script, "thumbnail_text", "") or not _is_valid_headline(getattr(script, "thumbnail_text", "")):
        script.thumbnail_text = hero_headline
    if not getattr(script, "thumbnail_subline", ""):
        script.thumbnail_subline = hero_subline
    return V17Meta(hero_headline=hero_headline, hero_subline=hero_subline, visual_family=core)
