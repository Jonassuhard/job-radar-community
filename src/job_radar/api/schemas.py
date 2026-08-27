"""Strict request and response contracts for the local API."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import ConfigDict, Field, JsonValue, StrictInt, StringConstraints

from job_radar.models import OfferFact, ScoreBreakdown, StrictModel

NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ApiModel(StrictModel):
    model_config = ConfigDict(extra="forbid")


class ProvenanceResponse(ApiModel):
    source: NonEmptyString
    external_id: NonEmptyString
    url: NonEmptyString


class OfferResponse(ApiModel):
    id: StrictInt = Field(ge=1)
    source: NonEmptyString
    url: NonEmptyString
    title: NonEmptyString
    company: NonEmptyString
    location: NonEmptyString
    contract: NonEmptyString
    remote: NonEmptyString
    description: NonEmptyString
    published_at: datetime
    facts: list[OfferFact]
    axes: list[ScoreBreakdown]
    relevance: StrictInt = Field(ge=0, le=100)
    confidence: StrictInt = Field(ge=0, le=100)
    freshness_days: StrictInt = Field(ge=0)
    decision: NonEmptyString
    score_version: NonEmptyString
    blocker: NonEmptyString | None = None
    provenance: list[ProvenanceResponse]


class CompareRequest(ApiModel):
    ids: list[Annotated[StrictInt, Field(ge=1)]] = Field(min_length=1, max_length=3)


class CompareResponse(ApiModel):
    offers: list[OfferResponse]
    missing: list[StrictInt]


class OfferPageResponse(ApiModel):
    items: list[OfferResponse]
    total: StrictInt = Field(ge=0)
    limit: StrictInt = Field(ge=1, le=100)
    offset: StrictInt = Field(ge=0)


class FeedbackRequest(ApiModel):
    value: NonEmptyString
    note: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] | None
    ) = None


class FeedbackResponse(ApiModel):
    id: StrictInt
    offer_id: StrictInt = Field(ge=1)
    value: NonEmptyString
    note: str | None
    created_at: datetime


class RefreshRequest(ApiModel):
    sources: list[NonEmptyString] = Field(default_factory=list)


class RefreshResponse(ApiModel):
    id: StrictInt
    status: NonEmptyString
    offers_seen: StrictInt = Field(ge=0)
    offers_saved: StrictInt = Field(ge=0)
    skipped_sources: list[str]


class RefreshStatusResponse(ApiModel):
    id: StrictInt
    source: NonEmptyString
    started_at: datetime
    finished_at: datetime | None
    status: NonEmptyString
    offers_seen: StrictInt = Field(ge=0)
    offers_saved: StrictInt = Field(ge=0)
    error_summary: str | None


class SavedViewRequest(ApiModel):
    name: NonEmptyString
    filters: dict[str, JsonValue]


class SavedViewResponse(SavedViewRequest):
    id: StrictInt
    created_at: datetime
    updated_at: datetime


class ValidationIssue(ApiModel):
    path: str
    message: str


class ImportResponse(ApiModel):
    preview: bool
    offers_received: StrictInt = Field(ge=0, le=500)
    offers_seen: StrictInt = Field(ge=0, le=500)
    offers_saved: StrictInt = Field(ge=0, le=500)
    errors: list[ValidationIssue]


class ConfigValidationResponse(ApiModel):
    valid: bool
    errors: list[ValidationIssue]


class RescoreResponse(ApiModel):
    offers_scored: StrictInt = Field(ge=0)
    score_version: str | None


class SkillCount(ApiModel):
    name: NonEmptyString
    count: StrictInt = Field(ge=1)


class MarketInsightsResponse(ApiModel):
    total_offers: StrictInt = Field(ge=0)
    decisions: dict[str, StrictInt]
    skills: list[SkillCount]


class SourceResponse(ApiModel):
    name: NonEmptyString
    mode: NonEmptyString
    enabled: bool
    available: bool
    automated: bool
    quota_per_day: StrictInt = Field(ge=0)
    credential_configured: bool
    health_status: str
    last_success_at: datetime | None
    quota_remaining: StrictInt | None
