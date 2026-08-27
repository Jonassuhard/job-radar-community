"""Explainable scoring with independent confidence and freshness."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from job_radar.config import AppConfig
from job_radar.config.models import normalize_source_key
from job_radar.models import OfferFact, RawOffer, ScoreBreakdown, ScoredOffer
from job_radar.pipeline.facts import extract_facts, salary_amount
from job_radar.pipeline.normalize import normalize_offer
from job_radar.pipeline.terms import contains_term, normalize_term


def _fold(value: str) -> str:
    return normalize_term(value)


def _contains(text: str, term: str) -> bool:
    return contains_term(text, term)


def _ratio(found: int, total: int) -> float:
    return found / total if total else 1.0


def _axis_ratio(
    name: str, offer: RawOffer, facts: list[OfferFact], config: AppConfig
) -> tuple[float, str]:
    fact_values = {(fact.name, _fold(fact.value)) for fact in facts}
    text = f"{offer.title}\n{offer.description}"

    if name == "role_fit":
        matches = sum(_contains(text, role) for role in config.profile.roles)
        return _ratio(
            matches, len(config.profile.roles)
        ), f"{matches}/{len(config.profile.roles)} target roles matched."
    if name == "skills":
        matches = sum(
            ("skill", _fold(skill)) in fact_values for skill in config.profile.skills
        )
        return _ratio(
            matches, len(config.profile.skills)
        ), f"{matches}/{len(config.profile.skills)} profile skills matched."
    if name == "location":
        matches = sum(
            _contains(offer.location, location) for location in config.search.locations
        )
        return (
            1.0 if matches else (1.0 if not config.search.locations else 0.0)
        ), f"Location matched {matches} configured targets."
    if name == "contract":
        matches = sum(
            _fold(offer.contract) == _fold(contract)
            for contract in config.search.contracts
        )
        return (
            1.0 if matches else (1.0 if not config.search.contracts else 0.0)
        ), f"Contract matched {matches} configured targets."
    if name == "work_mode":
        wanted = config.search.remote
        matched = wanted == "any" or _fold(offer.remote) == _fold(wanted)
        return float(
            matched
        ), f"Work mode {'matched' if matched else 'did not match'} {wanted}."
    if name == "language":
        matches = sum(
            ("language", _fold(language)) in fact_values
            for language in config.profile.languages
        )
        return _ratio(
            matches, len(config.profile.languages)
        ), f"{matches}/{len(config.profile.languages)} profile languages matched."
    if name == "seniority":
        matched = ("seniority", _fold(config.profile.seniority)) in fact_values
        return (
            float(matched),
            f"Seniority {'matched' if matched else 'did not match'} {config.profile.seniority}.",
        )
    if name == "required_terms":
        matches = sum(
            ("skill", _fold(term)) in fact_values for term in config.taxonomy.required
        )
        return _ratio(
            matches, len(config.taxonomy.required)
        ), f"{matches}/{len(config.taxonomy.required)} required terms matched."
    if name == "include_terms":
        matches = sum(_contains(text, term) for term in config.search.include_terms)
        return _ratio(
            matches, len(config.search.include_terms)
        ), f"{matches}/{len(config.search.include_terms)} search terms matched."
    if name == "salary":
        salaries = [salary_amount(fact.value) for fact in facts if fact.name == "salary"]
        known = [amount for amount in salaries if amount is not None]
        minimum = config.search.salary_minimum
        matched = bool(known) and (minimum == 0 or max(known) >= minimum)
        return float(matched), (
            "Salary met the configured minimum."
            if matched and minimum
            else f"Salary {'was' if matched else 'was not'} disclosed."
        )
    raise ValueError(f"unsupported scoring axis: {name}")


def _rule_applies(name: str, facts: list[OfferFact], *, positive: bool) -> bool:
    fact_names = {fact.name for fact in facts}
    if name == "salary_transparency":
        return "salary" in fact_names
    if name == "missing_salary":
        return "salary" not in fact_names
    if name == "missing_role_detail":
        return not any(fact.name == "role" and fact.confidence == 100 for fact in facts)
    raise ValueError(f"unsupported {'bonus' if positive else 'penalty'} rule: {name}")


def _apply_adjustment(
    axes: list[ScoreBreakdown],
    points: int,
    reason: str,
    *,
    increase: bool,
    limits: dict[str, int],
) -> list[ScoreBreakdown]:
    if not axes or points <= 0:
        return axes
    mutable = [axis.model_copy() for axis in axes]
    remaining = points
    indexes = range(len(mutable)) if increase else range(len(mutable) - 1, -1, -1)
    for index in indexes:
        current = mutable[index]
        capacity = limits[current.name] - current.points if increase else current.points
        applied = min(capacity, remaining)
        if applied:
            operator = "+" if increase else "-"
            mutable[index] = current.model_copy(
                update={
                    "points": current.points + applied
                    if increase
                    else current.points - applied,
                    "explanation": f"{current.explanation} {reason} ({operator}{applied}).",
                }
            )
            remaining -= applied
        if remaining == 0:
            break
    return mutable


def _blocker(
    offer: RawOffer,
    facts: list[OfferFact],
    confidence: int,
    config: AppConfig,
) -> str | None:
    text = f"{offer.title}\n{offer.description}"
    skill_values = {_fold(fact.value) for fact in facts if fact.name == "skill"}
    for rule in config.scoring.blockers:
        condition = rule.condition
        if condition == "excluded_term" and any(
            _contains(text, term) for term in config.search.exclude_terms
        ):
            return rule.name
        if condition == "required_term_missing" and any(
            _fold(term) not in skill_values for term in config.taxonomy.required
        ):
            return rule.name
    minimum_salary = config.search.salary_minimum
    known_salaries = [
        amount
        for fact in facts
        if fact.name == "salary"
        if (amount := salary_amount(fact.value)) is not None
    ]
    if minimum_salary and known_salaries and max(known_salaries) < minimum_salary:
        return "salary_minimum"
    minimum_confidence = config.scoring.thresholds.get("minimum_confidence", 0)
    if confidence < minimum_confidence:
        return "minimum_confidence"
    return None


def _decision(relevance: int, config: AppConfig, blocker: str | None) -> str:
    if not config.scoring.decisions:
        return "blocked" if blocker else "unscored"
    if blocker:
        return config.scoring.decisions[0].name
    eligible = [
        item.name for item in config.scoring.decisions if relevance >= item.min_score
    ]
    return eligible[-1] if eligible else config.scoring.decisions[0].name


def _confidence(facts: list[OfferFact], offer: RawOffer, config: AppConfig) -> int:
    fact_quality = (
        round(sum(fact.confidence for fact in facts) / len(facts)) if facts else 0
    )
    source = config.sources.sources.get(normalize_source_key(offer.source))
    source_quality = {"api": 95, "ats": 90, "manual_only": 65}.get(
        source.mode if source else "unknown", 60
    )
    return max(0, min(100, round((fact_quality + source_quality) / 2)))


def _score_version(config: AppConfig) -> str:
    payload = config.model_dump_json(exclude={"sources"})
    return f"config-{hashlib.sha256(payload.encode()).hexdigest()[:12]}"


def score_offer(
    offer: RawOffer,
    config: AppConfig,
    *,
    now: datetime | None = None,
) -> ScoredOffer:
    """Score an offer using only configured axes; freshness and confidence stay separate."""

    clock = now or datetime.now(UTC)
    if clock.tzinfo is None or offer.published_at.tzinfo is None:
        raise ValueError("scoring timestamps must include a timezone")
    normalized = normalize_offer(offer)
    normalized = normalized.model_copy(
        update={"source": normalize_source_key(normalized.source)}
    )
    facts = extract_facts(normalized, config)
    axes = []
    for axis in config.scoring.axes:
        ratio, explanation = _axis_ratio(axis.name, normalized, facts, config)
        axes.append(
            ScoreBreakdown(
                name=axis.name,
                points=max(0, min(axis.weight, round(axis.weight * ratio))),
                explanation=explanation,
            )
        )

    bonus = sum(
        rule.points
        for rule in config.scoring.bonuses
        if _rule_applies(rule.name, facts, positive=True)
    )
    bonus = min(bonus, config.scoring.caps.get("bonus", bonus))
    limits = {axis.name: axis.weight for axis in config.scoring.axes}
    axes = _apply_adjustment(
        axes,
        min(bonus, 100 - sum(axis.points for axis in axes)),
        "Configured bonus",
        increase=True,
        limits=limits,
    )
    penalty = sum(
        rule.points
        for rule in config.scoring.penalties
        if _rule_applies(rule.name, facts, positive=False)
    )
    penalty = min(penalty, config.scoring.caps.get("penalty", penalty))
    axes = _apply_adjustment(
        axes,
        min(penalty, sum(axis.points for axis in axes)),
        "Configured penalty",
        increase=False,
        limits=limits,
    )

    relevance = sum(axis.points for axis in axes)
    confidence = _confidence(facts, normalized, config)
    blocker = _blocker(normalized, facts, confidence, config)
    freshness_days = max(
        0,
        (
            clock.astimezone(UTC).date()
            - normalized.published_at.astimezone(UTC).date()
        ).days,
    )
    return ScoredOffer(
        offer=normalized,
        facts=facts,
        axes=axes,
        relevance=relevance,
        confidence=confidence,
        freshness_days=freshness_days,
        decision=_decision(relevance, config, blocker),
        score_version=_score_version(config),
        blocker=blocker,
    )
