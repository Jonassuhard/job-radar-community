"""Lossless normalization of connector offers."""

from __future__ import annotations

import re

from job_radar.models import RawOffer

_WHITESPACE = re.compile(r"\s+")


def _clean(value: str) -> str:
    return _WHITESPACE.sub(" ", value).strip()


def normalize_offer(offer: RawOffer) -> RawOffer:
    """Normalize comparable fields while preserving the raw source description."""

    return offer.model_copy(
        update={
            "external_id": offer.external_id.strip(),
            "source": _clean(offer.source).casefold(),
            "url": offer.url.strip(),
            "title": _clean(offer.title),
            "company": _clean(offer.company),
            "location": _clean(offer.location),
            "contract": _clean(offer.contract).casefold(),
            "remote": _clean(offer.remote).casefold(),
        }
    )
