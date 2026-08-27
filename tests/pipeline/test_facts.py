from __future__ import annotations

from job_radar.config import AppConfig
from job_radar.pipeline.facts import extract_facts


def test_extract_facts_is_deterministic_and_keeps_source_citations(
    config, matching_offer
):
    first = extract_facts(matching_offer, config)
    second = extract_facts(matching_offer, config)

    assert first == second
    assert {fact.name for fact in first} >= {
        "role",
        "skill",
        "seniority",
        "contract",
        "location",
        "remote",
        "salary",
        "language",
    }
    assert {fact.value for fact in first if fact.name == "skill"} >= {
        "workflow design",
        "data quality",
        "stakeholder coordination",
    }
    source_text = (
        f"{matching_offer.title}\n{matching_offer.location}\n"
        f"{matching_offer.contract}\n{matching_offer.remote}\n"
        f"{matching_offer.description}"
    )
    assert all(fact.citation in source_text for fact in first)


def test_taxonomy_aliases_produce_canonical_skill_facts(config, matching_offer):
    facts = extract_facts(matching_offer, config)
    workflow = next(
        fact
        for fact in facts
        if fact.name == "skill" and fact.value == "workflow design"
    )

    assert workflow.citation == "process design"
    assert workflow.confidence > 0


def test_fact_extraction_rejects_substring_collisions(config, matching_offer):
    payload = config.model_dump()
    payload["profile"]["roles"] = ["AI", "Go"]
    payload["profile"]["skills"] = ["AI", "Go"]
    payload["profile"]["seniority"] = "internship"
    payload["taxonomy"] = {"aliases": {}, "required": [], "preferred": [], "mentioned": []}
    collision_config = AppConfig.model_validate(payload)
    offer = matching_offer.model_copy(
        update={
            "title": "Paid Growth Manager",
            "description": "Google Analytics for international markets.",
        }
    )

    facts = extract_facts(offer, collision_config)

    assert [fact for fact in facts if fact.name == "skill"] == []
    assert [fact for fact in facts if fact.name == "seniority"] == []
    assert all(fact.citation not in {"ai", "Go", "intern"} for fact in facts)


def test_fact_extraction_supports_punctuated_skills_and_exact_quotes(config, matching_offer):
    payload = config.model_dump()
    payload["profile"]["skills"] = ["C++", "C#", ".NET", "Node.js"]
    payload["taxonomy"] = {"aliases": {}, "required": [], "preferred": [], "mentioned": []}
    punctuated_config = AppConfig.model_validate(payload)
    offer = matching_offer.model_copy(
        update={"description": "Production stack: C++, C#, .NET and Node.js."}
    )

    facts = extract_facts(offer, punctuated_config)

    citations = {
        fact.value: fact.citation for fact in facts if fact.name == "skill"
    }
    assert citations == {"C++": "C++", "C#": "C#", ".NET": ".NET", "Node.js": "Node.js"}
