from __future__ import annotations

from datetime import UTC, datetime

import pytest

from job_radar.config.models import AppConfig
from job_radar.models import RawOffer

FIXED_NOW = datetime(2026, 8, 26, 9, 30, tzinfo=UTC)


@pytest.fixture
def config() -> AppConfig:
    return AppConfig.model_validate(
        {
            "profile": {
                "roles": ["Product Operations Specialist"],
                "skills": [
                    "workflow design",
                    "data quality",
                    "stakeholder coordination",
                ],
                "evidence": [],
                "languages": ["English"],
                "seniority": "mid",
            },
            "search": {
                "locations": ["North District"],
                "contracts": ["permanent"],
                "remote": "hybrid",
                "salary_minimum": 0,
                "include_terms": ["operations"],
                "exclude_terms": ["commission-only"],
            },
            "scoring": {
                "axes": [
                    {"name": "role_fit", "weight": 35},
                    {"name": "skills", "weight": 25},
                    {"name": "location", "weight": 15},
                    {"name": "contract", "weight": 15},
                    {"name": "work_mode", "weight": 10},
                ],
                "decisions": [
                    {"name": "reject", "min_score": 0},
                    {"name": "monitor", "min_score": 45},
                    {"name": "review", "min_score": 70},
                    {"name": "prioritize", "min_score": 85},
                ],
                "thresholds": {"deduplication_similarity": 90},
                "caps": {},
                "bonuses": [],
                "penalties": [],
                "blockers": [
                    {"name": "excluded_term", "condition": "excluded_term"},
                ],
            },
            "sources": {
                "sources": {
                    "public_ats": {"mode": "ats"},
                    "local_demo": {"mode": "api"},
                    "linkedin": {"mode": "manual_only"},
                    "indeed": {"mode": "manual_only"},
                    "wttj": {"mode": "manual_only"},
                }
            },
            "taxonomy": {
                "aliases": {
                    "workflow design": ["process design"],
                    "data quality": ["data verification"],
                },
                "required": ["workflow design"],
                "preferred": ["data quality"],
                "mentioned": ["documentation"],
            },
        }
    )


@pytest.fixture
def matching_offer() -> RawOffer:
    return RawOffer(
        external_id="offer-001",
        source="public_ats",
        url="https://careers.example/offers/offer-001",
        title="Product Operations Specialist",
        company="Northstar Works",
        location="North District",
        contract="permanent",
        remote="hybrid",
        description=(
            "We need a mid-level Product Operations Specialist. "
            "You will lead process design, data verification, stakeholder coordination, "
            "and documentation in English. Salary: 55,000 EUR."
        ),
        published_at=FIXED_NOW,
    )
