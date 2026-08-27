"""Public contracts exchanged between connectors, the pipeline, and storage."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StringConstraints,
    field_validator,
    model_validator,
)

NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
ScorePoint = Annotated[StrictInt, Field(ge=0, le=100)]
NonNegativeInteger = Annotated[StrictInt, Field(ge=0)]


class StrictModel(BaseModel):
    """Reject undeclared fields so connector payloads remain explicit."""

    model_config = ConfigDict(extra="forbid")


class RawOffer(StrictModel):
    external_id: NonEmptyString
    source: NonEmptyString
    url: NonEmptyString
    title: NonEmptyString
    company: NonEmptyString
    location: NonEmptyString
    contract: NonEmptyString
    remote: NonEmptyString
    description: NonEmptyString
    published_at: datetime

    @field_validator("url")
    @classmethod
    def validate_public_url(cls, value: str) -> str:
        try:
            parsed = urlsplit(value)
            _port = parsed.port
        except ValueError as error:
            raise ValueError("url must be a valid HTTP or HTTPS URL") from error
        if (
            parsed.scheme.casefold() not in {"http", "https"}
            or not parsed.netloc
            or parsed.hostname is None
        ):
            raise ValueError("url must be a valid HTTP or HTTPS URL")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("url must not contain credentials")
        if any(character.isspace() or ord(character) < 32 for character in value):
            raise ValueError("url must not contain whitespace or control characters")
        return value


class OfferFact(StrictModel):
    name: NonEmptyString
    value: NonEmptyString
    citation: NonEmptyString
    confidence: ScorePoint


class ScoreBreakdown(StrictModel):
    name: NonEmptyString
    points: ScorePoint
    explanation: NonEmptyString


class ScoredOffer(StrictModel):
    offer: RawOffer
    facts: list[OfferFact] = Field(default_factory=list)
    axes: list[ScoreBreakdown] = Field(default_factory=list)
    relevance: ScorePoint
    confidence: ScorePoint
    freshness_days: NonNegativeInteger
    decision: NonEmptyString
    score_version: NonEmptyString
    blocker: NonEmptyString | None = None

    @model_validator(mode="after")
    def relevance_matches_axes(self) -> ScoredOffer:
        if self.relevance != sum(axis.points for axis in self.axes):
            raise ValueError("relevance must equal the sum of axis points")
        return self
