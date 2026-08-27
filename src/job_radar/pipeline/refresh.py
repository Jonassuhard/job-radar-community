"""Connector orchestration with explicit source-policy enforcement."""

from __future__ import annotations

import os
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import urlsplit

from job_radar.config import AppConfig
from job_radar.config.models import SourceConfig, normalize_source_key
from job_radar.db.store import RadarStore
from job_radar.models import RawOffer
from job_radar.pipeline.dedup import canonical_key, is_duplicate
from job_radar.pipeline.normalize import normalize_offer
from job_radar.pipeline.scoring import score_offer

_PROTECTED_MANUAL_SOURCES = frozenset({"linkedin", "indeed", "wttj"})
_PROTECTED_SOURCE_ALIASES = {
    "linkedin": "linkedin",
    "linkedinjobs": "linkedin",
    "indeed": "indeed",
    "indeedjobs": "indeed",
    "wttj": "wttj",
    "welcometothejungle": "wttj",
    "welcometothejunglejobs": "wttj",
}


class SourcePolicyError(ValueError):
    """Raised when an automated refresh targets a manual-only source."""


class Connector(Protocol):
    def fetch(self, config: AppConfig, client: object | None) -> Iterable[RawOffer]: ...


@dataclass(frozen=True, slots=True)
class RefreshResult:
    offers_seen: int
    offers_saved: int
    skipped_sources: tuple[str, ...] = ()


def _clock(now: datetime | None) -> datetime:
    clock = now or datetime.now(UTC)
    if clock.tzinfo is None:
        raise ValueError("refresh clock must include a timezone")
    return clock.astimezone(UTC)


def _source_name(value: str) -> str:
    normalized = " ".join(unicodedata.normalize("NFKC", value).split()).casefold()
    compact = "".join(character for character in normalized if character.isalnum())
    return _PROTECTED_SOURCE_ALIASES.get(compact, normalized)


def _protected_hostname(url: str) -> str | None:
    hostname = urlsplit(url).hostname
    if hostname is None:
        return None
    for label in hostname.rstrip(".").casefold().split("."):
        compact = "".join(character for character in label if character.isalnum())
        protected = _PROTECTED_SOURCE_ALIASES.get(compact)
        if protected is not None:
            return protected
    return None


def _configured_sources(config: AppConfig) -> dict[str, SourceConfig]:
    return {
        _source_name(name): source for name, source in config.sources.sources.items()
    }


def _reconcile(
    offers: Iterable[RawOffer], *, store: RadarStore, threshold: int
) -> tuple[list[RawOffer], list[str]]:
    representatives = store.list_canonical_offers()
    provenance_keys = store.provenance_canonical_keys()
    normalized_offers: list[RawOffer] = []
    canonical_keys: list[str] = []
    for raw_offer in offers:
        offer = normalize_offer(raw_offer)
        identity = (
            normalize_source_key(offer.source),
            offer.external_id.strip(),
        )
        stable_key = provenance_keys.get(identity)
        matched_key = stable_key or next(
            (
                key
                for key, existing in representatives
                if is_duplicate(offer, existing, threshold=threshold)
            ),
            None,
        )
        key = matched_key or canonical_key(offer)
        if stable_key is not None:
            for index, (representative_key, _existing) in enumerate(representatives):
                if representative_key == stable_key:
                    representatives[index] = (stable_key, offer)
                    break
        elif matched_key is None:
            representatives.append((key, offer))
        provenance_keys[identity] = key
        normalized_offers.append(offer)
        canonical_keys.append(key)
    return normalized_offers, canonical_keys


def _persist(
    offers: Iterable[RawOffer],
    *,
    config: AppConfig,
    store: RadarStore,
    now: datetime,
    preview: bool = False,
) -> RefreshResult:
    threshold = config.scoring.thresholds.get("deduplication_similarity", 90)
    reconciled, canonical_keys = _reconcile(offers, store=store, threshold=threshold)
    scored = [score_offer(offer, config, now=now) for offer in reconciled]
    if not preview:
        store.save_scored_batch(
            scored,
            canonical_keys=canonical_keys,
            processed_at=now,
        )
    return RefreshResult(
        offers_seen=len(reconciled),
        offers_saved=len(set(canonical_keys)),
    )


def import_offers(
    offers: Iterable[RawOffer],
    *,
    config: AppConfig,
    store: RadarStore,
    now: datetime | None = None,
    preview: bool = False,
) -> RefreshResult:
    """Process explicit user-provided offers, including manual-only sources."""

    return _persist(
        offers,
        config=config,
        store=store,
        now=_clock(now),
        preview=preview,
    )


def run_refresh(
    *,
    config: AppConfig,
    source_names: Iterable[str],
    store: RadarStore | None = None,
    connectors: Mapping[str, Connector] | None = None,
    client: object | None = None,
    now: datetime | None = None,
) -> RefreshResult:
    """Fetch enabled automated sources; unavailable network stubs are skipped."""

    names = tuple(source_names)
    configured = _configured_sources(config)
    for name in names:
        normalized_name = _source_name(name)
        source = configured.get(normalized_name)
        if normalized_name in _PROTECTED_MANUAL_SOURCES or (
            source is not None and source.mode == "manual_only"
        ):
            raise SourcePolicyError(f"source {name!r} is manual_only")

    if store is None:
        raise ValueError("store is required for automated refresh")

    available = connectors or {}
    collected: list[RawOffer] = []
    skipped: list[str] = []
    for name in names:
        normalized_name = _source_name(name)
        source = configured.get(normalized_name)
        connector = available.get(name)
        missing_key = bool(
            source and source.api_key_env and not os.environ.get(source.api_key_env)
        )
        if source is None or not source.enabled or connector is None or missing_key:
            skipped.append(name)
            continue
        for raw_offer in connector.fetch(config, client):
            offer = normalize_offer(raw_offer)
            returned_name = _source_name(offer.source)
            returned_source = configured.get(returned_name)
            protected_hostname = _protected_hostname(offer.url)
            if returned_name in _PROTECTED_MANUAL_SOURCES or protected_hostname or (
                returned_source is not None and returned_source.mode == "manual_only"
            ):
                raise SourcePolicyError(
                    f"connector {name!r} returned manual_only source or hostname "
                    f"{offer.source!r}"
                )
            if returned_name != normalized_name:
                raise SourcePolicyError(
                    f"offer source {offer.source!r} does not match connector {name!r}"
                )
            collected.append(offer)

    result = _persist(collected, config=config, store=store, now=_clock(now))
    return RefreshResult(
        offers_seen=result.offers_seen,
        offers_saved=result.offers_saved,
        skipped_sources=tuple(skipped),
    )
