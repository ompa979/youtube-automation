"""Viral-first content scoring and framing for broad-audience Shorts.

This module deliberately does not predict or guarantee virality. It scores
content characteristics that are useful for broad Shorts packaging:
curiosity, emotional consequence, novelty, visual potential, clarity, and
specificity. The score is an internal selection gate, not a platform forecast.
"""
from __future__ import annotations

import re

COMPARISON = (" vs ", " versus ", "difference", "different", "compare", "compared")
CURIOSITY = (
    "why ", "how ", "actually", "what happens", "what changes", "why does",
    "secret", "hidden", "reason", "behind", "really"
)
CONTRADICTION = ("but ", "isn't", "not what", "you think", "counterintuitive", "opposite")
EMOTION = (
    "money", "fear", "embarrass", "mistake", "regret", "stress", "confidence",
    "success", "failure", "lonely", "attention", "habit", "decision", "risk", "career",
)
VISUAL = (
    "brain", "phone", "money", "graph", "curve", "before", "after", "transformation",
    "flow", "process", "machine", "robot", "screen", "timeline", "experiment", "door",
    "clock", "signal", "network", "brain", "eye", "light", "space", "planet", "fire",
)
FAST = ("shortcut", "fast", "quick", "in seconds", "without", "step by step", "easy")
NUMBER_MARKERS = tuple(str(i) for i in range(10)) + ("one", "two", "three", "five", "ten", "first", "next")
GENERIC = (
    "overview", "introduction", "basic concepts", "functions", "meaning", "what is",
    "basics", "definition", "generic tips", "success tips", "daily motivation",
    "motivation quotes", "motivational quotes"
)
CLICKBAIT = (
    "guaranteed", "get rich quick", "make you rich", "instant success", "secret hack",
    "you won't believe", "shocking", "100%", "cure", "miracle"
)


def _norm(topic: str) -> str:
    return " " + re.sub(r"\s+", " ", (topic or "").strip().lower()) + " "


def viral_fit(topic: str) -> float:
    """Return a 0-100 broad-audience Shorts content score."""
    t = _norm(topic)
    score = 20.0

    broad = 10.0
    if any(x in t for x in EMOTION):
        broad += 8.0
    if any(x in t for x in CURIOSITY):
        broad += 8.0
    if len(t.split()) <= 16:
        broad += 4.0
    score += broad

    if any(x in t for x in CURIOSITY):
        score += 16.0
    if any(x in t for x in COMPARISON):
        score += 10.0
    if any(x in t for x in CONTRADICTION):
        score += 9.0
    if any(x in t for x in EMOTION):
        score += 7.0
    if any(x in t for x in VISUAL):
        score += 10.0
    if any(x in t for x in FAST):
        score += 5.0
    if any(x in t for x in NUMBER_MARKERS):
        score += 4.0

    if any(x in t for x in GENERIC):
        score -= 12.0
    if any(x in t for x in CLICKBAIT):
        score -= 22.0

    # Reward a concrete mechanism or consequence. Broad statements without one
    # tend to produce weak, static Shorts.
    mechanism_markers = ("because", "when", "before", "after", "causes", "changes", "works")
    if any(x in t for x in mechanism_markers):
        score += 6.0
    else:
        score -= 2.0

    return round(max(0.0, min(100.0, score)), 2)


def viral_angle(topic: str) -> str:
    """Return a creative framing hint for the script generator."""
    t = (topic or "").lower()
    if any(x in t for x in CONTRADICTION):
        return "CONTRADICTION: open with the surprising reversal, then prove it with one concrete mechanism."
    if any(x in t for x in COMPARISON):
        return "HEAD-TO-HEAD: make the difference visually obvious in the first seconds, then show the consequence."
    if any(x in t for x in EMOTION):
        return "HUMAN CONSEQUENCE: start with the personal consequence, then explain the mechanism behind it."
    if any(x in t for x in FAST):
        return "TIME-SAVER: reveal a genuinely useful shortcut or mental model and demonstrate it once."
    if any(x in t for x in CURIOSITY):
        return "WHY-LOOP: open on the surprising result, then reveal the hidden mechanism step by step."
    return "VISUAL TRANSFORMATION: show one clear before→after or input→result change that explains the idea."
