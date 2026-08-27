"""Deterministic fact extraction with source-backed citations."""

from __future__ import annotations

import re
from collections.abc import Iterable

from job_radar.config import AppConfig
from job_radar.models import OfferFact, RawOffer
from job_radar.pipeline.terms import find_term

_SALARY = re.compile(
    r"(?<!\w)(?:salary\s*[:\-]?\s*)?\d{2,3}(?:[,.\s]\d{3})?\s*(?:EUR|USD|GBP|€|£|\$)",
    re.IGNORECASE,
)
_SENIORITY = (
    ("internship", ("internship", "intern")),
    ("junior", ("junior", "entry-level", "entry level")),
    ("mid", ("mid-level", "mid level", "midweight")),
    ("senior", ("senior",)),
    ("lead", ("lead",)),
    ("principal", ("principal",)),
)


def _find_excerpt(text: str, terms: Iterable[str]) -> tuple[str, bool] | None:
    match = find_term(text, terms)
    return (match.citation, match.term_index > 0) if match else None


def salary_amount(citation: str) -> int | None:
    """Parse the integer salary form accepted by the deterministic salary matcher."""

    match = re.search(r"\d{2,3}(?:[,\.\s]\d{3})?", citation)
    if match is None:
        return None
    digits = re.sub(r"\D", "", match.group())
    return int(digits) if digits else None


def _term_map(config: AppConfig) -> dict[str, tuple[str, ...]]:
    canonical_terms = dict.fromkeys(
        [
            *config.profile.skills,
            *config.taxonomy.required,
            *config.taxonomy.preferred,
            *config.taxonomy.mentioned,
            *config.taxonomy.aliases,
        ]
    )
    return {
        term: (term, *config.taxonomy.aliases.get(term, [])) for term in canonical_terms
    }


def extract_facts(offer: RawOffer, config: AppConfig) -> list[OfferFact]:
    """Extract comparable facts without probabilistic inference or rewritten quotes."""

    facts: list[OfferFact] = []
    searchable = f"{offer.title}\n{offer.description}"

    role_match = _find_excerpt(searchable, config.profile.roles)
    if role_match:
        citation, _ = role_match
        facts.append(
            OfferFact(name="role", value=citation, citation=citation, confidence=100)
        )
    else:
        facts.append(
            OfferFact(
                name="role", value=offer.title, citation=offer.title, confidence=85
            )
        )

    for skill, terms in _term_map(config).items():
        match = _find_excerpt(searchable, terms)
        if match:
            citation, used_alias = match
            facts.append(
                OfferFact(
                    name="skill",
                    value=skill,
                    citation=citation,
                    confidence=90 if used_alias else 100,
                )
            )

    for seniority, terms in _SENIORITY:
        match = _find_excerpt(searchable, terms)
        if match:
            citation, _ = match
            facts.append(
                OfferFact(
                    name="seniority",
                    value=seniority,
                    citation=citation,
                    confidence=95,
                )
            )
            break

    for name, value in (
        ("contract", offer.contract),
        ("location", offer.location),
        ("remote", offer.remote),
    ):
        facts.append(OfferFact(name=name, value=value, citation=value, confidence=100))

    salary = _SALARY.search(offer.description)
    if salary:
        citation = offer.description[salary.start() : salary.end()]
        facts.append(
            OfferFact(name="salary", value=citation, citation=citation, confidence=95)
        )

    for language in config.profile.languages:
        match = _find_excerpt(searchable, (language,))
        if match:
            citation, _ = match
            facts.append(
                OfferFact(
                    name="language",
                    value=language,
                    citation=citation,
                    confidence=100,
                )
            )

    return facts
