from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from job_radar.config import AppConfig
from job_radar.pipeline.scoring import score_offer

from .conftest import FIXED_NOW


def test_score_explains_every_axis(config, matching_offer):
    result = score_offer(matching_offer, config, now=FIXED_NOW)

    assert result.relevance == sum(axis.points for axis in result.axes)
    assert {axis.name for axis in result.axes} == set(config.scoring.axis_names)
    assert all(axis.explanation for axis in result.axes)
    assert result.freshness_days == 0
    assert result.decision == "prioritize"


def test_freshness_does_not_change_relevance(config, matching_offer):
    fresh = score_offer(matching_offer, config, now=FIXED_NOW)
    old_offer = matching_offer.model_copy(
        update={"published_at": matching_offer.published_at - timedelta(days=120)}
    )
    old = score_offer(old_offer, config, now=FIXED_NOW)

    assert fresh.relevance == old.relevance
    assert old.freshness_days == 120


def test_source_quality_changes_confidence_not_relevance(config, matching_offer):
    automated = score_offer(matching_offer, config, now=FIXED_NOW)
    manual_offer = matching_offer.model_copy(update={"source": "linkedin"})
    manual = score_offer(manual_offer, config, now=FIXED_NOW)

    assert automated.relevance == manual.relevance
    assert manual.confidence < automated.confidence


def test_normalized_custom_source_key_controls_confidence(config, matching_offer):
    payload = config.model_dump()
    payload["sources"]["sources"][" ÉCOLE  ATS "] = {"mode": "ats"}
    custom_config = AppConfig.model_validate(payload)
    custom_offer = matching_offer.model_copy(update={"source": " Ｅ\u0301ＣＯＬＥ  ATS "})
    unknown_offer = matching_offer.model_copy(update={"source": "unknown source"})

    configured = score_offer(custom_offer, custom_config, now=FIXED_NOW)
    unknown = score_offer(unknown_offer, custom_config, now=FIXED_NOW)

    assert configured.confidence > unknown.confidence
    assert configured.offer.source == "école ats"


def test_configured_excluded_term_blocks_without_becoming_an_axis(
    config, matching_offer
):
    blocked_offer = matching_offer.model_copy(
        update={
            "description": matching_offer.description + " This role is commission-only."
        }
    )

    result = score_offer(blocked_offer, config, now=FIXED_NOW)

    assert result.blocker == "excluded_term"
    assert result.decision == "reject"
    assert {axis.name for axis in result.axes} == set(config.scoring.axis_names)


def test_configured_bonus_is_capped_and_stays_within_axis_weights(
    config, matching_offer
):
    payload = config.model_dump()
    payload["scoring"]["bonuses"] = [{"name": "salary_transparency", "points": 10}]
    payload["scoring"]["caps"] = {"bonus": 5}
    bonus_config = AppConfig.model_validate(payload)
    partial_offer = matching_offer.model_copy(
        update={
            "description": (
                "Product Operations Specialist using process design in English. "
                "Salary: 55,000 EUR."
            )
        }
    )
    baseline = score_offer(partial_offer, config, now=FIXED_NOW)

    result = score_offer(partial_offer, bonus_config, now=FIXED_NOW)

    weights = {axis.name: axis.weight for axis in bonus_config.scoring.axes}
    assert result.relevance == baseline.relevance + 5
    assert all(axis.points <= weights[axis.name] for axis in result.axes)
    assert any("Configured bonus" in axis.explanation for axis in result.axes)


def test_relevance_boundaries_are_exactly_zero_and_one_hundred(config, matching_offer):
    matching = score_offer(matching_offer, config, now=FIXED_NOW)
    non_matching = matching_offer.model_copy(
        update={
            "title": "Finance Director",
            "location": "South District",
            "contract": "fixed_term",
            "remote": "onsite",
            "description": "Lead accounting consolidation in French.",
        }
    )

    rejected = score_offer(non_matching, config, now=FIXED_NOW)

    assert matching.relevance == 100
    assert rejected.relevance == 0
    assert all(axis.points == 0 for axis in rejected.axes)


def test_freshness_uses_utc_calendar_days_across_timezones(config, matching_offer):
    published = datetime(2026, 8, 26, 23, 30, tzinfo=timezone(timedelta(hours=2)))
    now = datetime(2026, 8, 27, 0, 30, tzinfo=UTC)
    offer = matching_offer.model_copy(update={"published_at": published})

    result = score_offer(offer, config, now=now)

    assert result.freshness_days == 1


def test_future_utc_publication_is_clamped_to_zero_days(config, matching_offer):
    published = datetime(2026, 8, 26, 23, 30, tzinfo=timezone(-timedelta(hours=4)))
    now = datetime(2026, 8, 27, 1, 0, tzinfo=UTC)
    offer = matching_offer.model_copy(update={"published_at": published})

    result = score_offer(offer, config, now=now)

    assert result.freshness_days == 0


def test_bonus_and_penalty_can_exhaust_capacity_across_multiple_axes(
    config, matching_offer
):
    bonus_payload = config.model_dump()
    bonus_payload["scoring"]["bonuses"] = [
        {"name": "salary_transparency", "points": 60}
    ]
    bonus_payload["scoring"]["caps"] = {"bonus": 60}
    bonus_config = AppConfig.model_validate(bonus_payload)
    no_match_with_salary = matching_offer.model_copy(
        update={
            "title": "Finance Director",
            "location": "South District",
            "contract": "fixed_term",
            "remote": "onsite",
            "description": "Accounting consolidation. Salary: 55,000 EUR.",
        }
    )

    boosted = score_offer(no_match_with_salary, bonus_config, now=FIXED_NOW)

    assert boosted.relevance == 60
    assert [axis.points for axis in boosted.axes[:2]] == [35, 25]

    penalty_payload = config.model_dump()
    penalty_payload["scoring"]["penalties"] = [{"name": "missing_salary", "points": 60}]
    penalty_payload["scoring"]["caps"] = {"penalty": 60}
    penalty_config = AppConfig.model_validate(penalty_payload)
    no_salary = matching_offer.model_copy(
        update={
            "description": matching_offer.description.replace("Salary: 55,000 EUR.", "")
        }
    )

    reduced = score_offer(no_salary, penalty_config, now=FIXED_NOW)

    assert reduced.relevance == 40
    assert sum(axis.points == 0 for axis in reduced.axes) >= 3


def test_substring_collisions_cannot_create_relevance(config, matching_offer):
    payload = config.model_dump()
    payload["profile"]["roles"] = ["AI", "Go"]
    payload["profile"]["skills"] = ["AI", "Go"]
    payload["taxonomy"] = {"aliases": {}, "required": [], "preferred": [], "mentioned": []}
    payload["scoring"]["axes"] = [
        {"name": "role_fit", "weight": 50},
        {"name": "skills", "weight": 50},
    ]
    collision_config = AppConfig.model_validate(payload)
    offer = matching_offer.model_copy(
        update={
            "title": "Paid Growth Manager",
            "description": "Google Analytics for international markets.",
        }
    )

    result = score_offer(offer, collision_config, now=FIXED_NOW)

    assert result.relevance == 0
    assert all(axis.points == 0 for axis in result.axes)


def test_every_supported_axis_has_an_effective_matching_rule(config, matching_offer):
    payload = config.model_dump()
    payload["scoring"]["axes"] = [
        {"name": name, "weight": 10}
        for name in (
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
        )
    ]
    all_axes_config = AppConfig.model_validate(payload)

    result = score_offer(matching_offer, all_axes_config, now=FIXED_NOW)

    assert result.relevance == 100
    assert all(axis.points == 10 for axis in result.axes)


def test_known_salary_below_minimum_forces_reject_with_blocker(config, matching_offer):
    payload = config.model_dump()
    payload["search"]["salary_minimum"] = 60_000
    salary_config = AppConfig.model_validate(payload)

    result = score_offer(matching_offer, salary_config, now=FIXED_NOW)

    assert result.relevance == 100
    assert result.blocker == "salary_minimum"
    assert result.decision == "reject"


def test_minimum_confidence_forces_reject_with_blocker(config, matching_offer):
    payload = config.model_dump()
    payload["scoring"]["thresholds"]["minimum_confidence"] = 100
    confidence_config = AppConfig.model_validate(payload)

    result = score_offer(matching_offer, confidence_config, now=FIXED_NOW)

    assert result.confidence < 100
    assert result.blocker == "minimum_confidence"
    assert result.decision == "reject"
