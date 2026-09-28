"""Per-topic subject-area classification, shared by visuals.py and render.py.

The niche config (content_plan.json) only has two broad buckets
("exam_concepts", "science_explainers") but a single niche's topic list
spans geography, history, science and economy questions. Giving every
video in a niche the same accent color / grade / prompt style makes them
feel identical even though the *subject matter* is completely different
scene to scene. This module keyword-matches the topic string once per
video and returns one of four "subject areas" that every premium layer
(image prompt style, accent color, color grade, transition choice) keys
off of, so a geography video actually looks/feels different from a
history video even inside the same niche.
"""
from __future__ import annotations

SUBJECT_AREAS = ("geography", "history", "science", "economy", "psychology", "india")

_KEYWORDS: dict[str, tuple[str, ...]] = {
    "geography": (
        "monsoon", "climate", "weather", "altitude", "ocean", "orbit", "satellite",
        "gps", "el nino", "wind", "map", "river", "continent", "atmosphere",
        "geography", "rainfall", "cyclone", "terrain", "latitude", "longitude",
    ),
    "history": (
        "constitution", "fundamental right", "directive principle", "parliament",
        "history", "independence", "colonial", "freedom struggle", "ancient",
        "medieval", "empire", "dynasty", "movement", "collective responsibility",
    ),
    "economy": (
        "inflation", "repo rate", "fiscal deficit", "trade balance", "gdp",
        "economy", "economic", "interest", "bank", "rbi", "sebi", "nabard",
        "budget", "tax", "market", "currency", "opportunity cost", "deficit",
        "balance of payments",
    ),
    "science": (
        "acid", "base", "reaction", "chemical", "physics", "biology", "cell",
        "antibod", "antibiotic", "vaccine", "resistance", "pressure", "frequency",
        "resonance", "transformer", "voltage", "semiconductor", "ph scale",
        "activation energy", "octopus", "blood", "metal", "spoon", "sky is blue",
        "scattering", "light", "quantum", "crispr", "dna", "neuron", "atom",
        "particle", "triple point", "cone", "wavelength",
    ),
    "psychology": (
        "brain", "memory", "sleep", "dream", "stress", "habit", "mood", "emotion",
        "yawn", "goosebump", "cry", "music", "scroll", "social media", "exercise",
        "gut", "bacteria", "cold shower", "gratitude", "loneliness", "immune",
        "hippocampus", "neurotransmitter", "dopamine", "serotonin", "mind",
        "body", "wake up", "morning", "screen", "eyes", "study", "forget",
    ),
    "india": (
        "india", "indian", "upsc", "ias", "mumbai", "delhi", "railway", "isro",
        "monsoon", "zero", "vedic", "ancient", "chandragupta", "iit", "dabbawala",
        "polio", "solar", "chip", "engineer", "vegetarian", "language", "dialect",
        "operation flood", "milk", "mars", "circumference", "astronomers",
    ),
}

# Accent palette (hex, ffmpeg 0xRRGGBB form) per subject area — used for
# on-screen text tint, exam badge, and the outro card background.
ACCENT_HEX: dict[str, str] = {
    "geography": "0x0D3B4E",  # Deep Ocean Night — teal-black
    "history": "0x5C3A1E",    # Aged Manuscript — warm sepia-brown
    "science": "0x3A1E5C",    # Neon Lab — violet-black
    "economy": "0x2B2E33",    # Clean Power — editorial grey
    "psychology": "0x1A3A2E",  # Deep Forest — calm teal-green (mind/wellness)
    "india":      "0x6B2D00",  # Saffron Deep — India's national color
    "default": "0x2B2B2E",
}

# ffmpeg colorbalance shadows/midtones/highlights (rs,gs,bs,rm,gm,bm,rh,gh,bh)
# per subject area, layered on top of a base eq() pass for contrast/saturation.
COLOR_GRADE: dict[str, str] = {
    "geography": "colorbalance=rs=-0.12:gs=-0.02:bs=0.18:rm=-0.06:gm=0.0:bm=0.10:rh=-0.02:gh=0.0:bh=0.06,eq=contrast=1.08:saturation=1.05:brightness=-0.01",
    "history": "colorbalance=rs=0.14:gs=0.04:bs=-0.14:rm=0.10:gm=0.02:bm=-0.08:rh=0.06:gh=0.0:bh=-0.04,eq=contrast=1.03:saturation=0.82:brightness=0.01:gamma_r=1.05",
    "science": "colorbalance=rs=0.06:gs=-0.06:bs=0.20:rm=0.02:gm=-0.04:bm=0.14:rh=0.0:gh=-0.02:bh=0.08,eq=contrast=1.10:saturation=1.12",
    "economy": "eq=contrast=1.06:saturation=0.88:brightness=0.0",
    "psychology": "colorbalance=rs=-0.06:gs=0.08:bs=-0.04:rm=-0.02:gm=0.06:bm=-0.02:rh=0.0:gh=0.04:bh=-0.02,eq=contrast=1.05:saturation=1.08:brightness=0.01",
    "india":      "colorbalance=rs=0.18:gs=0.06:bs=-0.18:rm=0.12:gm=0.04:bm=-0.10:rh=0.08:gh=0.02:bh=-0.06,eq=contrast=1.06:saturation=1.18:brightness=0.01",
    "default": "eq=contrast=1.045:saturation=1.035:brightness=0.004",
}

# Short "exam badge" label per niche key (layer 2 typography).
NICHE_BADGE: dict[str, str] = {
    "bank_it_officer": "IBPS SO IT",
    "bank_reasoning_quant": "BANK PO",
    "banking_awareness": "BANK EXAMS",
    "rbi_economy": "RBI GRADE B",
    "bank_english": "BANK ENGLISH",
    "exam_concepts": "UPSC 2026",
    "science_explainers": "SCIENCE",
    "why_things_work": "DID YOU KNOW",
    "india_facts": "INDIA",
    "mind_and_body": "BRAIN FACTS",
    "default": "LEARN TODAY",
}

# Extra Flux prompt clause per subject area (layer 1 imagery), layered on
# top of the existing niche visual_style suffix rather than replacing it.
SUBJECT_AREA_IMAGE_SUFFIX: dict[str, str] = {
    "geography": (
        ", satellite/aerial drama, sweeping top-down or oblique perspective, "
        "deep teal-and-navy atmosphere, visible weather systems or landmasses, "
        "sense of planetary scale"
    ),
    "history": (
        ", aged manuscript and archival mood, warm sepia tones, parchment or "
        "stone texture, period-accurate detail, weight of history in the lighting"
    ),
    "science": (
        ", neon-lit laboratory energy, violet and electric-blue rim lighting, "
        "glassware or molecular/mechanical precision, futuristic clinical mood"
    ),
    "economy": (
        ", clean editorial finance mood, crisp neutral-grey studio lighting, "
        "minimal geometric composition, glossy magazine-cover polish"
    ),
    "psychology": (
        ", soft bioluminescent mind-glow aesthetic, teal-and-emerald brain visualization, "
        "ethereal neural connections, warm focused light on the human form, "
        "calming yet intellectually stimulating atmosphere"
    ),
    "india": (
        ", vibrant saffron-and-teal editorial mood, Indian cultural richness, "
        "golden-hour warm tones, cinematic scale suggesting pride and achievement, "
        "modern India meets ancient wisdom visual language"
    ),
    "default": "",
}


def classify_subject_area(topic: str) -> str:
    """Keyword-match a topic string to one of SUBJECT_AREAS. Falls back to
    'economy' only if nothing else matches better — most exam-prep topics
    default reasonably well because the keyword lists are broad; anything
    truly unmatched returns 'default' territory via ACCENT_HEX['default'].
    """
    text = (topic or "").lower()
    scores = {area: 0 for area in SUBJECT_AREAS}
    for area, words in _KEYWORDS.items():
        for w in words:
            if w in text:
                scores[area] += 1
    best_area = max(scores, key=scores.get)
    if scores[best_area] == 0:
        return "default"
    return best_area
