"""Deterministic normalization, fact extraction, scoring, and refresh pipeline."""

from job_radar.pipeline.dedup import canonical_key, is_duplicate
from job_radar.pipeline.facts import extract_facts
from job_radar.pipeline.normalize import normalize_offer
from job_radar.pipeline.refresh import (
    RefreshResult,
    SourcePolicyError,
    import_offers,
    run_refresh,
)
from job_radar.pipeline.scoring import score_offer

__all__ = [
    "RefreshResult",
    "SourcePolicyError",
    "canonical_key",
    "extract_facts",
    "import_offers",
    "is_duplicate",
    "normalize_offer",
    "run_refresh",
    "score_offer",
]
