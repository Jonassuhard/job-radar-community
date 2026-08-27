"""Strict local JSON offer import contracts shared by CLI and API."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from job_radar.models import RawOffer

MAX_IMPORT_BYTES = 2 * 1024 * 1024
MAX_IMPORT_OFFERS = 500


@dataclass(frozen=True, slots=True)
class ImportIssue:
    path: str
    message: str


class OfferImportError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        issues: list[ImportIssue],
        status_code: int = 422,
    ) -> None:
        super().__init__(message)
        self.issues = tuple(issues)
        self.status_code = status_code


class _InvalidJson(ValueError):
    pass


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _InvalidJson(f"duplicate object key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise _InvalidJson(f"non-finite number: {value}")


def _error(message: str, path: str, *, status_code: int = 422) -> OfferImportError:
    return OfferImportError(
        message,
        issues=[ImportIssue(path=path, message=message)],
        status_code=status_code,
    )


def parse_offer_import(payload: bytes) -> list[RawOffer]:
    """Parse one bounded, strict JSON array and report every indexed model error."""

    if len(payload) > MAX_IMPORT_BYTES:
        raise _error("Import file must not exceed 2 MiB", "file", status_code=413)
    try:
        document = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, _InvalidJson) as error:
        raise _error("Import file must contain strict UTF-8 JSON", "json") from error
    if not isinstance(document, list):
        raise _error("Import JSON root must be an array", "root")
    if len(document) > MAX_IMPORT_OFFERS:
        raise _error("Import file must contain at most 500 offers", "root")

    offers: list[RawOffer] = []
    issues: list[ImportIssue] = []
    for index, item in enumerate(document):
        try:
            offer = RawOffer.model_validate(item)
        except ValidationError as error:
            issues.extend(
                ImportIssue(
                    path=".".join(str(part) for part in (index, *detail["loc"])),
                    message=detail["msg"],
                )
                for detail in error.errors()
            )
            continue
        if offer.published_at.tzinfo is None:
            issues.append(
                ImportIssue(
                    path=f"{index}.published_at",
                    message="Timestamp must include a timezone",
                )
            )
            continue
        offers.append(offer)
    if issues:
        raise OfferImportError("Import file contains invalid offers", issues=issues)
    return offers
