from __future__ import annotations

from datetime import UTC, datetime

from job_radar.models import RawOffer
from job_radar.pipeline.normalize import normalize_offer


def test_normalize_offer_cleans_structured_fields_without_rewriting_source_text():
    description = "First source sentence.\n\n  Second source sentence stays verbatim."
    raw = RawOffer(
        external_id=" offer-001 ",
        source=" Public_ATS ",
        url=" https://careers.example/offers/offer-001 ",
        title="  Product   Operations\nSpecialist ",
        company=" Northstar   Works ",
        location=" North   District ",
        contract=" Permanent ",
        remote=" Hybrid ",
        description=description,
        published_at=datetime(2026, 8, 26, 9, 30, tzinfo=UTC),
    )

    normalized = normalize_offer(raw)

    assert normalized.external_id == "offer-001"
    assert normalized.source == "public_ats"
    assert normalized.title == "Product Operations Specialist"
    assert normalized.company == "Northstar Works"
    assert normalized.location == "North District"
    assert normalized.contract == "permanent"
    assert normalized.remote == "hybrid"
    assert normalized.description == description
    assert normalized.published_at == raw.published_at
