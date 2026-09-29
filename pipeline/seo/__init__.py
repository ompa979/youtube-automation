"""pipeline.seo — SEO V3 package exports."""
from __future__ import annotations

from .keyword_clusters import KeywordCluster, KEYWORD_CLUSTERS, SYNONYM_MAP, get_cluster_for_topic
from .title_generator import TitleMode, generate_seo_title, pick_title_mode, extract_problem_hook
from .description_generator import generate_v3_description, generate_v3_tags
from .keyword_guard import (
    KeywordDensityResult,
    validate_keyword_density,
    auto_repair_narration,
    auto_repair_screen_text,
)
from .seo_score import (
    SEOScore,
    RetentionScore,
    PublishScore,
    calculate_seo_score,
    calculate_retention_score,
    calculate_final_publish_score,
)
from .topic_memory import TopicMemory, SERIES_CLUSTERS, CompletedVideo

__all__ = [
    "KeywordCluster",
    "KEYWORD_CLUSTERS",
    "SYNONYM_MAP",
    "get_cluster_for_topic",
    "TitleMode",
    "generate_seo_title",
    "pick_title_mode",
    "extract_problem_hook",
    "generate_v3_description",
    "generate_v3_tags",
    "KeywordDensityResult",
    "validate_keyword_density",
    "auto_repair_narration",
    "auto_repair_screen_text",
    "SEOScore",
    "RetentionScore",
    "PublishScore",
    "calculate_seo_score",
    "calculate_retention_score",
    "calculate_final_publish_score",
    "TopicMemory",
    "SERIES_CLUSTERS",
    "CompletedVideo",
]
