"""Stable canonicalization and conservative duplicate detection."""

from __future__ import annotations

import json
import unicodedata
from difflib import SequenceMatcher

from job_radar.models import RawOffer

_EMOJI_JOINERS = frozenset({"\u200d", "\ufe0f"})


def _canonical_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    characters = [
        character
        if unicodedata.category(character)[0] in {"L", "M", "N", "S"}
        or character in _EMOJI_JOINERS
        else " "
        for character in normalized
    ]
    return " ".join("".join(characters).split())


def _canonical_components(offer: RawOffer) -> tuple[str, str, str]:
    components: list[str] = []
    for name, value in (
        ("company", offer.company),
        ("title", offer.title),
        ("location", offer.location),
    ):
        canonical = _canonical_text(value)
        if not canonical:
            raise ValueError(f"{name} canonical component cannot be empty")
        components.append(canonical)
    return components[0], components[1], components[2]


def canonical_key(offer: RawOffer) -> str:
    """Return the inspectable company/title/location identity for an offer."""

    return json.dumps(
        _canonical_components(offer), ensure_ascii=False, separators=(",", ":")
    )


def _similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, left, right).ratio() * 100


def is_duplicate(left: RawOffer, right: RawOffer, *, threshold: int = 90) -> bool:
    """Require every identity component to clear the configured similarity threshold."""

    if not 0 <= threshold <= 100:
        raise ValueError("deduplication threshold must be between 0 and 100")
    left_components = _canonical_components(left)
    right_components = _canonical_components(right)
    return all(
        _similarity(left_value, right_value) >= threshold
        for left_value, right_value in zip(
            left_components, right_components, strict=True
        )
    )
