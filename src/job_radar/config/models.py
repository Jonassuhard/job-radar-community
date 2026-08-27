"""Strict schemas for the local Job Radar configuration files."""

from __future__ import annotations

import unicodedata
from itertools import pairwise
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    field_validator,
    model_validator,
)

NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
EnvironmentVariableName = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Z][A-Z0-9_]*$"),
]
ScorePoint = Annotated[StrictInt, Field(ge=0, le=100)]
NonNegativeInteger = Annotated[StrictInt, Field(ge=0)]
AxisName = Literal[
    "role_fit",
    "skills",
    "location",
    "contract",
    "work_mode",
    "language",
    "seniority",
    "required_terms",
    "include_terms",
    "salary",
]
DecisionName = Literal["reject", "monitor", "review", "prioritize"]
BlockerCondition = Literal[
    "excluded_term",
    "required_term_missing",
]


def normalize_source_key(value: str) -> str:
    """Return the canonical identity shared by source config and runtime data."""

    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


class StrictModel(BaseModel):
    """Base class that rejects configuration drift instead of ignoring it."""

    model_config = ConfigDict(extra="forbid")


class ProfileConfig(StrictModel):
    roles: list[NonEmptyString] = Field(default_factory=list)
    skills: list[NonEmptyString] = Field(default_factory=list)
    evidence: list[NonEmptyString] = Field(default_factory=list)
    languages: list[NonEmptyString] = Field(default_factory=list)
    seniority: NonEmptyString = "unspecified"


class SearchConfig(StrictModel):
    locations: list[NonEmptyString] = Field(default_factory=list)
    contracts: list[NonEmptyString] = Field(default_factory=list)
    remote: Literal["any", "remote", "hybrid", "onsite"] = "any"
    salary_minimum: NonNegativeInteger = 0
    include_terms: list[NonEmptyString] = Field(default_factory=list)
    exclude_terms: list[NonEmptyString] = Field(default_factory=list)


class ScoreAxis(StrictModel):
    name: AxisName
    weight: ScorePoint


class DecisionThreshold(StrictModel):
    name: DecisionName
    min_score: ScorePoint


class AdjustmentRule(StrictModel):
    name: NonEmptyString
    points: ScorePoint


class BlockingRule(StrictModel):
    name: NonEmptyString
    condition: BlockerCondition


class ScoringConfig(StrictModel):
    axes: list[ScoreAxis] = Field(min_length=1)
    decisions: list[DecisionThreshold] = Field(min_length=4, max_length=4)
    thresholds: dict[NonEmptyString, ScorePoint] = Field(default_factory=dict)
    caps: dict[NonEmptyString, ScorePoint] = Field(default_factory=dict)
    bonuses: list[AdjustmentRule] = Field(default_factory=list)
    penalties: list[AdjustmentRule] = Field(default_factory=list)
    blockers: list[BlockingRule] = Field(default_factory=list)

    @property
    def axis_names(self) -> tuple[str, ...]:
        return tuple(axis.name for axis in self.axes)

    @field_validator("axes")
    @classmethod
    def validate_axes(cls, axes: list[ScoreAxis]) -> list[ScoreAxis]:
        if sum(axis.weight for axis in axes) != 100:
            raise ValueError("axis weights must total 100")
        if len({axis.name for axis in axes}) != len(axes):
            raise ValueError("axis names must be unique")
        return axes

    @field_validator("decisions")
    @classmethod
    def validate_decisions(cls, decisions: list[DecisionThreshold]) -> list[DecisionThreshold]:
        decision_scores = [decision.min_score for decision in decisions]
        if any(
            current <= previous for previous, current in pairwise(decision_scores)
        ):
            raise ValueError("decision min_score values must be strictly increasing")
        if len({decision.name for decision in decisions}) != len(decisions):
            raise ValueError("decision names must be unique")
        expected = ["reject", "monitor", "review", "prioritize"]
        if [decision.name for decision in decisions] != expected:
            raise ValueError(f"decision names must be exactly {', '.join(expected)}")
        return decisions

    @field_validator("thresholds")
    @classmethod
    def validate_thresholds(
        cls, thresholds: dict[str, int]
    ) -> dict[str, int]:
        unknown = set(thresholds) - {"minimum_confidence", "deduplication_similarity"}
        if unknown:
            raise ValueError(f"unsupported thresholds: {', '.join(sorted(unknown))}")
        return thresholds

    @field_validator("caps")
    @classmethod
    def validate_caps(cls, caps: dict[str, int]) -> dict[str, int]:
        unknown = set(caps) - {"bonus", "penalty"}
        if unknown:
            raise ValueError(f"unsupported caps: {', '.join(sorted(unknown))}")
        return caps

    @field_validator("bonuses")
    @classmethod
    def validate_bonuses(cls, rules: list[AdjustmentRule]) -> list[AdjustmentRule]:
        unknown = {rule.name for rule in rules} - {"salary_transparency"}
        if unknown:
            raise ValueError(f"unsupported bonus rules: {', '.join(sorted(unknown))}")
        return rules

    @field_validator("penalties")
    @classmethod
    def validate_penalties(cls, rules: list[AdjustmentRule]) -> list[AdjustmentRule]:
        unknown = {rule.name for rule in rules} - {"missing_salary", "missing_role_detail"}
        if unknown:
            raise ValueError(f"unsupported penalty rules: {', '.join(sorted(unknown))}")
        return rules


class SourceConfig(StrictModel):
    mode: Literal["api", "ats", "manual_only"]
    enabled: StrictBool = True
    quota_per_day: NonNegativeInteger = 0
    api_key_env: EnvironmentVariableName | None = None

    @model_validator(mode="after")
    def reject_secrets_for_manual_sources(self) -> SourceConfig:
        if self.mode == "manual_only" and self.api_key_env is not None:
            raise ValueError("manual_only sources cannot declare api_key_env")
        return self


class SourcesConfig(StrictModel):
    sources: dict[NonEmptyString, SourceConfig] = Field(default_factory=dict)

    @field_validator("sources", mode="before")
    @classmethod
    def normalize_source_keys(cls, sources: object) -> object:
        if not isinstance(sources, dict):
            return sources
        normalized: dict[str, object] = {}
        for key, source in sources.items():
            if not isinstance(key, str):
                # Pydantic wraps ValueError into the public validation contract.
                raise ValueError("source keys must be strings")  # noqa: TRY004
            normalized_key = normalize_source_key(key)
            if not normalized_key:
                raise ValueError("source keys cannot be empty")
            if normalized_key in normalized:
                raise ValueError("source keys must be unique after normalization")
            normalized[normalized_key] = source
        return normalized


class TaxonomyConfig(StrictModel):
    aliases: dict[NonEmptyString, list[NonEmptyString]] = Field(default_factory=dict)
    required: list[NonEmptyString] = Field(default_factory=list)
    preferred: list[NonEmptyString] = Field(default_factory=list)
    mentioned: list[NonEmptyString] = Field(default_factory=list)


class AppConfig(StrictModel):
    profile: ProfileConfig
    search: SearchConfig
    scoring: ScoringConfig
    sources: SourcesConfig
    taxonomy: TaxonomyConfig
