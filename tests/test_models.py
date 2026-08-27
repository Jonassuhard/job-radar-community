from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from job_radar.models import RawOffer


def _offer_payload(url: str) -> dict[str, object]:
    return {
        "external_id": "offer-001",
        "source": "public_ats",
        "url": url,
        "title": "Product Operations Analyst",
        "company": "Northstar Works",
        "location": "Paris",
        "contract": "permanent",
        "remote": "hybrid",
        "description": "Coordinate product operations and analytics.",
        "published_at": datetime(2026, 8, 26, 9, 30, tzinfo=UTC),
    }


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "ftp://jobs.example.com/offers/1",
        "https://demo:password@jobs.example.com/offers/1",
        "https:///offers/1",
    ],
)
def test_raw_offer_rejects_non_web_or_credentialed_urls(url: str) -> None:
    with pytest.raises(ValidationError, match="url"):
        RawOffer.model_validate(_offer_payload(url))


@pytest.mark.parametrize(
    "url",
    [
        "http://jobs.example.com/offers/1",
        "https://jobs.example.com/offers/1?from=radar#details",
    ],
)
def test_raw_offer_accepts_http_and_https_urls_without_credentials(url: str) -> None:
    assert RawOffer.model_validate(_offer_payload(url)).url == url
