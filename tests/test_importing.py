from __future__ import annotations

import json

import pytest

from job_radar.importing import (
    MAX_IMPORT_BYTES,
    MAX_IMPORT_OFFERS,
    OfferImportError,
    parse_offer_import,
)


def _offer(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "external_id": "manual-001",
        "source": "linkedin",
        "url": "https://www.linkedin.com/jobs/view/manual-001",
        "title": "Product Operations Analyst",
        "company": "Example Workshop",
        "location": "Paris",
        "contract": "permanent",
        "remote": "hybrid",
        "description": "Product operations and analytics.",
        "published_at": "2026-08-27T08:00:00Z",
    }
    payload.update(overrides)
    return payload


def test_parser_accepts_a_strict_json_array_of_manual_offers() -> None:
    offers = parse_offer_import(json.dumps([_offer()]).encode())

    assert len(offers) == 1
    assert offers[0].source == "linkedin"
    assert offers[0].external_id == "manual-001"


@pytest.mark.parametrize(
    ("payload", "expected_path"),
    [
        (json.dumps({"offer": _offer()}).encode(), "root"),
        (json.dumps([_offer(unexpected=True)]).encode(), "0.unexpected"),
        (json.dumps([_offer(published_at="2026-08-27T08:00:00")]).encode(), "0.published_at"),
        (json.dumps([_offer(url="javascript:alert(1)")]).encode(), "0.url"),
        (b'[{"source":"linkedin","source":"indeed"}]', "json"),
        (b"[NaN]", "json"),
    ],
)
def test_parser_rejects_non_strict_or_ambiguous_json(
    payload: bytes, expected_path: str
) -> None:
    with pytest.raises(OfferImportError) as caught:
        parse_offer_import(payload)

    assert expected_path in {issue.path for issue in caught.value.issues}


def test_parser_rejects_more_than_five_hundred_offers() -> None:
    payload = json.dumps([_offer(external_id=f"manual-{index}") for index in range(501)]).encode()

    with pytest.raises(OfferImportError, match="500") as caught:
        parse_offer_import(payload)

    assert MAX_IMPORT_OFFERS == 500
    assert caught.value.status_code == 422


def test_parser_rejects_payloads_larger_than_two_mib() -> None:
    payload = b"[" + b" " * MAX_IMPORT_BYTES + b"]"

    with pytest.raises(OfferImportError, match="2 MiB") as caught:
        parse_offer_import(payload)

    assert MAX_IMPORT_BYTES == 2 * 1024 * 1024
    assert caught.value.status_code == 413
