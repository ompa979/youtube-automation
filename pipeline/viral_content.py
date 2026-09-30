"""Virality-first content scoring for ExamCracker Shorts.

This module does not promise or predict virality. It filters for content
characteristics that are useful for Shorts packaging: curiosity, contrast,
common mistakes, surprising mechanisms, concrete consequences, and strong
visual/exam payoff.
"""
from __future__ import annotations

import re

COMPARISON = (" vs ", " versus ", "difference", "different")
CURIOSITY = ("why ", "how ", "actually", "what happens", "what changes", "why does")
TRAP = ("mistake", "trap", "wrong", "confuse", "confusion", "catch", "misread", "eliminate")
CONSEQUENCE = (
    "money", "payment", "bank", "reserve", "npa", "inflation", "borrower", "transaction",
    "password", "security", "network", "query", "output", "answer", "option", "result",
)
VISUAL = (
    "flow", "handshake", "layer", "table", "query", "key", "diagram", "process", "tree",
    "graph", "route", "transaction", "formula", "ratio", "timeline", "node", "binary",
)
FAST = ("shortcut", "fast", "quick", "without ", "step by step", "eliminate", "save time")
NUMBER_MARKERS = ("1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "three", "two", "one", "90-day")
BROAD = ("overview", "introduction", "basic concepts", "functions", "meaning", "what is", "basics", "definition")


def viral_fit(topic: str) -> float:
    """Return a 0-100 content-angle score. Higher means more Shorts-friendly."""
    t = " " + re.sub(r"\s+", " ", (topic or "").strip().lower()) + " "
    score = 38.0

    if any(x in t for x in COMPARISON):
        score += 16.0
    if any(x in t for x in CURIOSITY):
        score += 15.0
    if any(x in t for x in TRAP):
        score += 14.0
    if any(x in t for x in CONSEQUENCE):
        score += 7.0
    if any(x in t for x in VISUAL):
        score += 9.0
    if any(x in t for x in FAST):
        score += 8.0
    if any(x in t for x in NUMBER_MARKERS):
        score += 6.0

    broad_hits = sum(x in t for x in BROAD)
    score -= min(15.0, broad_hits * 5.0)

    # Penalize low-curiosity titles that are merely taxonomic.
    if not any(x in t for x in COMPARISON + CURIOSITY + TRAP + FAST):
        score -= 8.0

    return round(max(0.0, min(100.0, score)), 2)


def viral_angle(topic: str) -> str:
    """Choose a content framing hint for the script prompt."""
    t = (topic or "").lower()
    if any(x in t for x in TRAP):
        return "TRAP REVEAL: show the tempting wrong idea, then overturn it with the rule."
    if any(x in t for x in COMPARISON):
        return "HEAD-TO-HEAD: make the difference visible immediately; show exactly when each side wins."
    if any(x in t for x in FAST):
        return "TIME-SAVER: show the shortest correct route and why it works."
    if any(x in t for x in CURIOSITY):
        return "WHY-LOOP: open with the surprising consequence, then explain the mechanism that causes it."
    return "VISUAL MECHANISM: show one concrete transformation from input to result with an exam takeaway."
