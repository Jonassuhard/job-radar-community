"""Public Radar routes backed by the local configuration and SQLite store."""

from __future__ import annotations

import ipaddress
import json
import os
import secrets
import shutil
import sqlite3
import stat
import unicodedata
from collections import Counter
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

import yaml
from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import JSONResponse
from pydantic import Field, ValidationError

from job_radar.api.schemas import (
    CompareRequest,
    CompareResponse,
    ConfigValidationResponse,
    FeedbackRequest,
    FeedbackResponse,
    ImportResponse,
    MarketInsightsResponse,
    OfferPageResponse,
    OfferResponse,
    RefreshRequest,
    RefreshResponse,
    RefreshStatusResponse,
    RescoreResponse,
    SavedViewRequest,
    SavedViewResponse,
    SourceResponse,
)
from job_radar.config.defaults import EXAMPLE_FILENAMES
from job_radar.config.loader import (
    ACTIVE_GENERATION_POINTER,
    GENERATIONS_DIRECTORY,
    ConfigError,
    load_config,
)
from job_radar.config.models import AppConfig, normalize_source_key
from job_radar.connectors import remote_connector_available
from job_radar.db.store import RadarStore
from job_radar.importing import MAX_IMPORT_BYTES, OfferImportError, parse_offer_import
from job_radar.local_security import PrivatePathError, ensure_private_directory
from job_radar.models import RawOffer
from job_radar.pipeline.refresh import (
    SourcePolicyError,
    run_refresh,
)
from job_radar.pipeline.refresh import import_offers as persist_import_offers
from job_radar.pipeline.scoring import score_offer

router = APIRouter()
SessionToken = Annotated[str | None, Header(alias="X-Job-Radar-Token")]

_RANKED_OFFERS_SQL = """
WITH ranked AS (
    SELECT
        os.offer_id,
        os.source,
        os.external_id,
        os.source_url,
        os.raw_payload_json,
        os.fingerprint AS source_fingerprint,
        s.relevance,
        s.confidence,
        s.freshness_days,
        s.decision,
        s.blocker,
        s.axes_json,
        s.score_version,
        ROW_NUMBER() OVER (
            PARTITION BY os.offer_id
            ORDER BY s.confidence DESC, s.relevance DESC, os.source, os.external_id
        ) AS provenance_rank
    FROM offer_sources AS os
    JOIN offer_scores AS s
      ON s.offer_id = os.offer_id
     AND s.source_fingerprint = os.fingerprint
    WHERE s.profile_id = 'default'
      AND json_extract(os.raw_payload_json, '$._quarantine_reason') IS NULL
), canonical AS (
    SELECT
           o.id,
           o.canonical_key,
           o.status,
           ranked.source,
           ranked.external_id,
           ranked.source_url,
           ranked.source_fingerprint,
           COALESCE(json_extract(ranked.raw_payload_json, '$.title'), o.title) AS title,
           COALESCE(json_extract(ranked.raw_payload_json, '$.company'), o.company) AS company,
           COALESCE(json_extract(ranked.raw_payload_json, '$.location'), o.location) AS location,
           COALESCE(json_extract(ranked.raw_payload_json, '$.contract'), o.contract) AS contract,
           COALESCE(json_extract(ranked.raw_payload_json, '$.remote'), o.remote) AS remote,
           COALESCE(
               json_extract(ranked.raw_payload_json, '$.description'), o.description
           ) AS description,
           COALESCE(
               json_extract(ranked.raw_payload_json, '$.published_at'), o.published_at
           ) AS published_at,
           ranked.relevance,
           ranked.confidence,
           ranked.decision,
           ranked.blocker,
           ranked.axes_json,
           ranked.score_version,
           MAX(
               0,
               CAST(
                   julianday(date(?)) - julianday(
                       date(COALESCE(
                           json_extract(ranked.raw_payload_json, '$.published_at'),
                           o.published_at
                       ))
                   ) AS INTEGER
               )
           ) AS current_freshness_days
    FROM offers AS o
    JOIN ranked ON ranked.offer_id = o.id
    WHERE ranked.provenance_rank = 1
)
"""

_SORT_SQL = {
    "relevance_desc": "c.relevance DESC, c.confidence DESC, c.id ASC",
    "relevance_asc": "c.relevance ASC, c.confidence DESC, c.id ASC",
    "confidence_desc": "c.confidence DESC, c.relevance DESC, c.id ASC",
    "freshness_asc": "c.current_freshness_days ASC, c.relevance DESC, c.id ASC",
    "published_desc": "julianday(c.published_at) DESC, c.id ASC",
}


class ConfigWriteError(OSError):
    """A local configuration update failed and was rolled back."""


class RefreshExecutionError(RuntimeError):
    """A refresh failed after its local status was finalized."""


class RefreshPolicyFailure(RefreshExecutionError):
    """A refresh target violated the public source policy."""


def _store(request: Request) -> RadarStore:
    return request.app.state.store


def _config_dir(request: Request) -> Path:
    return request.app.state.settings.config_dir


def _config(request: Request) -> AppConfig:
    try:
        return load_config(_config_dir(request))
    except ConfigError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


def require_session(request: Request, token: SessionToken = None) -> None:
    expected = request.app.state.session_token
    if token is None or not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")


def require_loopback(request: Request) -> None:
    host = request.client.host if request.client else ""
    if host == "testclient" and request.app.state.settings.allow_testclient:
        return
    try:
        is_loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        is_loopback = host.casefold() == "localhost"
    if not is_loopback:
        raise HTTPException(status_code=403, detail="Local access only")


def _connect(store: RadarStore) -> sqlite3.Connection:
    connection = sqlite3.connect(store.path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.create_function(
        "unicode_casefold", 1, _unicode_casefold, deterministic=True
    )
    return connection


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _unicode_casefold(value: str | None) -> str:
    if value is None:
        return ""
    return unicodedata.normalize("NFKC", value).casefold()


def _record_source_health(
    connection: sqlite3.Connection,
    source_names: list[str],
    *,
    status_value: str,
    updated_at: str,
    successful: bool = False,
) -> None:
    for source_name in source_names:
        normalized_source = normalize_source_key(source_name)
        connection.execute(
            """
            INSERT INTO source_health (source, status, last_success_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(source) DO UPDATE SET
                status = excluded.status,
                last_success_at = CASE
                    WHEN excluded.last_success_at IS NOT NULL
                    THEN excluded.last_success_at
                    ELSE source_health.last_success_at
                END,
                updated_at = excluded.updated_at
            """,
            (
                normalized_source,
                status_value,
                updated_at if successful else None,
                updated_at,
            ),
        )


async def _read_import_body(request: Request) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_size = int(content_length)
        except ValueError:
            declared_size = 0
        if declared_size > MAX_IMPORT_BYTES:
            raise OfferImportError(
                "Import file must not exceed 2 MiB",
                issues=[],
                status_code=413,
            )
    payload = bytearray()
    async for chunk in request.stream():
        payload.extend(chunk)
        if len(payload) > MAX_IMPORT_BYTES:
            raise OfferImportError(
                "Import file must not exceed 2 MiB",
                issues=[],
                status_code=413,
            )
    return bytes(payload)


def _offer_conditions(
    *,
    decision: str | None = None,
    source: str | None = None,
    query: str | None = None,
    min_score: int = 0,
    min_confidence: int = 0,
    contract: str | None = None,
    location: str | None = None,
    remote: str | None = None,
    max_freshness: int | None = None,
    offer_ids: list[int] | None = None,
) -> tuple[str, list[object]]:
    clauses = ["c.status = 'active'", "c.relevance >= ?", "c.confidence >= ?"]
    parameters: list[object] = [min_score, min_confidence]
    for column, value in (
        ("decision", decision),
        ("contract", contract),
        ("location", location),
        ("remote", remote),
    ):
        if value is not None:
            clauses.append(f"unicode_casefold(c.{column}) = unicode_casefold(?)")
            parameters.append(value)
    if source is not None:
        clauses.append(
            "EXISTS (SELECT 1 FROM offer_sources filtered_source "
            "WHERE filtered_source.offer_id = c.id "
            "AND unicode_casefold(filtered_source.source) = unicode_casefold(?) "
            "AND json_extract(filtered_source.raw_payload_json, "
            "'$._quarantine_reason') IS NULL)"
        )
        parameters.append(normalize_source_key(source))
    if query:
        clauses.append(
            "(unicode_casefold(c.title || ' ' || c.company || ' ' || c.location || ' ' || "
            "c.description) LIKE ? ESCAPE '\\' OR EXISTS "
            "(SELECT 1 FROM offer_sources searched_source "
            "WHERE searched_source.offer_id = c.id "
            "AND unicode_casefold(searched_source.external_id) LIKE ? ESCAPE '\\' "
            "AND json_extract(searched_source.raw_payload_json, "
            "'$._quarantine_reason') IS NULL))"
        )
        escaped_query = (
            _unicode_casefold(query)
            .replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        needle = f"%{escaped_query}%"
        parameters.extend((needle, needle))
    if max_freshness is not None:
        clauses.append("c.current_freshness_days <= ?")
        parameters.append(max_freshness)
    if offer_ids is not None:
        if not offer_ids:
            clauses.append("0")
        else:
            clauses.append(f"c.id IN ({','.join('?' for _ in offer_ids)})")
            parameters.extend(offer_ids)
    return " AND ".join(clauses), parameters


def _materialize_offers(
    connection: sqlite3.Connection, rows: list[sqlite3.Row]
) -> list[OfferResponse]:
    if not rows:
        return []
    offer_ids = [row["id"] for row in rows]
    placeholders = ",".join("?" for _ in offer_ids)
    provenance: dict[int, list[dict[str, str]]] = {
        offer_id: [] for offer_id in offer_ids
    }
    for row in connection.execute(
        f"SELECT offer_id, source, external_id, source_url FROM offer_sources "
        f"WHERE offer_id IN ({placeholders}) AND json_extract("
        "raw_payload_json, '$._quarantine_reason') IS NULL "
        "ORDER BY offer_id, source, external_id",
        offer_ids,
    ):
        provenance[row["offer_id"]].append(
            {
                "source": row["source"],
                "external_id": row["external_id"],
                "url": row["source_url"],
            }
        )
    facts: dict[tuple[int, str], list[dict[str, object]]] = {}
    for row in connection.execute(
        f"SELECT offer_id, source_fingerprint, name, value, citation, confidence "
        f"FROM offer_facts WHERE offer_id IN ({placeholders}) ORDER BY offer_id, id",
        offer_ids,
    ):
        facts.setdefault((row["offer_id"], row["source_fingerprint"]), []).append(
            {
                "name": row["name"],
                "value": row["value"],
                "citation": row["citation"],
                "confidence": row["confidence"],
            }
        )
    return [
        OfferResponse(
            id=row["id"],
            source=row["source"],
            url=row["source_url"],
            title=row["title"],
            company=row["company"],
            location=row["location"],
            contract=row["contract"],
            remote=row["remote"],
            description=row["description"],
            published_at=row["published_at"],
            facts=facts.get((row["id"], row["source_fingerprint"]), []),
            axes=json.loads(row["axes_json"]),
            relevance=row["relevance"],
            confidence=row["confidence"],
            freshness_days=row["current_freshness_days"],
            decision=row["decision"],
            score_version=row["score_version"],
            blocker=row["blocker"],
            provenance=provenance[row["id"]],
        )
        for row in rows
    ]


def _offers_by_ids(store: RadarStore, offer_ids: list[int]) -> dict[int, OfferResponse]:
    conditions, parameters = _offer_conditions(offer_ids=offer_ids)
    current_date = _utc_now().astimezone(UTC).date().isoformat()
    with _connect(store) as connection:
        rows = connection.execute(
            f"{_RANKED_OFFERS_SQL} SELECT c.* FROM canonical c WHERE {conditions} "
            "ORDER BY c.id",
            [current_date, *parameters],
        ).fetchall()
        offers = _materialize_offers(connection, rows)
    return {offer.id: offer for offer in offers}


def _validation_issues(error: ValidationError) -> list[dict[str, str]]:
    return [
        {
            "path": ".".join(str(part) for part in detail["loc"]),
            "message": detail["msg"],
        }
        for detail in error.errors()
    ]


def rescore_store(
    store: RadarStore, config: AppConfig, *, now: datetime | None = None
) -> RescoreResponse:
    """Recompute every provenance in one store batch."""

    clock = now or _utc_now()
    store.repair_legacy_data()
    with _connect(store) as connection:
        rows = connection.execute(
            """
            SELECT o.canonical_key, os.raw_payload_json
                FROM offer_sources AS os
                JOIN offers AS o ON o.id = os.offer_id
                WHERE json_extract(
                    os.raw_payload_json, '$._quarantine_reason'
                ) IS NULL
                ORDER BY o.canonical_key, os.source, os.external_id
            """
        ).fetchall()
    offers = [
        RawOffer.model_validate(json.loads(row["raw_payload_json"])) for row in rows
    ]
    scored = [score_offer(offer, config, now=clock) for offer in offers]
    store.save_scored_batch(
        scored,
        canonical_keys=[row["canonical_key"] for row in rows],
        processed_at=clock,
        reactivate=False,
    )
    return RescoreResponse(
        offers_scored=len(scored),
        score_version=scored[0].score_version if scored else None,
    )


def refresh_store(
    store: RadarStore,
    config: AppConfig,
    sources: list[str],
    *,
    now: datetime | None = None,
) -> RefreshResponse:
    """Run connector orchestration and retain a sanitized local status record."""

    clock = (now or _utc_now()).astimezone(UTC)
    sources = [normalize_source_key(source) for source in sources]
    label = ",".join(sources) if sources else "all"
    with _connect(store) as connection:
        cursor = connection.execute(
            "INSERT INTO refresh_runs (source, started_at, status) VALUES (?, ?, 'running')",
            (label, clock.isoformat()),
        )
        run_id = cursor.lastrowid
    try:
        result = run_refresh(
            config=config,
            source_names=sources,
            store=store,
            now=clock,
        )
        finished_at = _utc_now().isoformat()
        with _connect(store) as connection:
            connection.execute(
                "UPDATE refresh_runs SET finished_at = ?, status = 'completed', "
                "offers_seen = ?, offers_saved = ? WHERE id = ?",
                (finished_at, result.offers_seen, result.offers_saved, run_id),
            )
            for source_name in sources:
                source_status = (
                    "skipped" if source_name in result.skipped_sources else "ok"
                )
                _record_source_health(
                    connection,
                    [source_name],
                    status_value=source_status,
                    updated_at=finished_at,
                    successful=source_status == "ok",
                )
    except SourcePolicyError:
        failed_at = _utc_now().isoformat()
        with _connect(store) as connection:
            connection.execute(
                "UPDATE refresh_runs SET finished_at = ?, status = 'failed', "
                "error_summary = ? WHERE id = ?",
                (failed_at, "Refresh rejected by source policy", run_id),
            )
            _record_source_health(
                connection,
                sources,
                status_value="failed",
                updated_at=failed_at,
            )
        raise RefreshPolicyFailure("Refresh rejected by source policy") from None
    except Exception:  # noqa: BLE001 - every pipeline failure must finalize the run
        failed_at = _utc_now().isoformat()
        with _connect(store) as connection:
            connection.execute(
                "UPDATE refresh_runs SET finished_at = ?, status = 'failed', "
                "error_summary = ? WHERE id = ?",
                (failed_at, "Refresh failed", run_id),
            )
            _record_source_health(
                connection,
                sources,
                status_value="failed",
                updated_at=failed_at,
            )
        raise RefreshExecutionError("Refresh failed") from None
    return RefreshResponse(
        id=run_id,
        status="completed",
        offers_seen=result.offers_seen,
        offers_saved=result.offers_saved,
        skipped_sources=list(result.skipped_sources),
    )


@router.get("/health", tags=["system"])
def health(store: Annotated[RadarStore, Depends(_store)]) -> dict[str, int | str]:
    with _connect(store) as connection:
        schema_version = connection.execute("PRAGMA user_version").fetchone()[0]
    return {"status": "ok", "schema_version": schema_version}


@router.get("/api/session", include_in_schema=False)
def bootstrap_session(request: Request) -> JSONResponse:
    require_loopback(request)
    return JSONResponse(
        {"token": request.app.state.session_token},
        headers={
            "Cache-Control": "no-store, no-cache",
            "Pragma": "no-cache",
        },
    )


@router.post(
    "/api/import",
    response_model=ImportResponse,
    dependencies=[Depends(require_session)],
    tags=["offers"],
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "array",
                        "maxItems": 500,
                        "items": {"type": "object", "additionalProperties": False},
                    }
                }
            },
        }
    },
)
async def import_manual_offers(
    request: Request,
    store: Annotated[RadarStore, Depends(_store)],
    preview: Annotated[bool, Query()] = False,
) -> ImportResponse:
    try:
        offers = parse_offer_import(await _read_import_body(request))
        result = persist_import_offers(
            offers,
            config=_config(request),
            store=store,
            preview=preview,
        )
    except OfferImportError as error:
        detail = [
            {"path": issue.path, "message": issue.message} for issue in error.issues
        ] or [{"path": "file", "message": str(error)}]
        raise HTTPException(status_code=error.status_code, detail=detail) from error
    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail=[{"path": "offers", "message": str(error)}],
        ) from error
    return ImportResponse(
        preview=preview,
        offers_received=len(offers),
        offers_seen=result.offers_seen,
        offers_saved=result.offers_saved,
        errors=[],
    )


@router.get("/api/offers", response_model=OfferPageResponse, tags=["offers"])
def list_offers(
    store: Annotated[RadarStore, Depends(_store)],
    decision: str | None = None,
    source: str | None = None,
    query: str | None = Query(default=None, alias="q"),
    min_score: int = Query(default=0, ge=0, le=100),
    min_confidence: int = Query(default=0, ge=0, le=100),
    contract: str | None = None,
    location: str | None = None,
    remote: str | None = None,
    max_freshness: int | None = Query(default=None, ge=0),
    sort: Literal[
        "relevance_desc",
        "relevance_asc",
        "confidence_desc",
        "freshness_asc",
        "published_desc",
    ] = "relevance_desc",
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> OfferPageResponse:
    conditions, parameters = _offer_conditions(
        decision=decision,
        source=source,
        query=query,
        min_score=min_score,
        min_confidence=min_confidence,
        contract=contract,
        location=location,
        remote=remote,
        max_freshness=max_freshness,
    )
    current_date = _utc_now().astimezone(UTC).date().isoformat()
    with _connect(store) as connection:
        total = connection.execute(
            f"{_RANKED_OFFERS_SQL} SELECT COUNT(*) FROM canonical c WHERE {conditions}",
            [current_date, *parameters],
        ).fetchone()[0]
        rows = connection.execute(
            f"{_RANKED_OFFERS_SQL} SELECT c.* FROM canonical c WHERE {conditions} "
            f"ORDER BY {_SORT_SQL[sort]} LIMIT ? OFFSET ?",
            [current_date, *parameters, limit, offset],
        ).fetchall()
        items = _materialize_offers(connection, rows)
    return OfferPageResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/api/offers/compare", response_model=CompareResponse, tags=["offers"])
def compare_offers(
    store: Annotated[RadarStore, Depends(_store)],
    ids: Annotated[
        list[Annotated[int, Field(ge=1)]], Query(min_length=1, max_length=3)
    ],
) -> CompareResponse:
    found = _offers_by_ids(store, ids)
    return CompareResponse(
        offers=[found[offer_id] for offer_id in ids if offer_id in found],
        missing=[offer_id for offer_id in ids if offer_id not in found],
    )


@router.post("/api/offers/compare", response_model=CompareResponse, tags=["offers"])
def compare_offers_body(
    payload: CompareRequest,
    store: Annotated[RadarStore, Depends(_store)],
) -> CompareResponse:
    return compare_offers(store, payload.ids)


@router.get("/api/offers/{offer_id}", response_model=OfferResponse, tags=["offers"])
def offer_detail(
    offer_id: int, store: Annotated[RadarStore, Depends(_store)]
) -> OfferResponse:
    offer = _offers_by_ids(store, [offer_id]).get(offer_id)
    if offer is None:
        raise HTTPException(status_code=404, detail="Offer not found")
    return offer


@router.post(
    "/api/offers/{offer_id}/feedback",
    response_model=FeedbackResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_session)],
    tags=["offers"],
)
def create_feedback(
    offer_id: int,
    payload: FeedbackRequest,
    store: Annotated[RadarStore, Depends(_store)],
) -> FeedbackResponse:
    created_at = _utc_now()
    with _connect(store) as connection:
        row = connection.execute(
            "SELECT id FROM offers WHERE id = ?",
            (offer_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Offer not found")
        cursor = connection.execute(
            "INSERT INTO user_feedback (offer_id, value, note, created_at) VALUES (?, ?, ?, ?)",
            (row["id"], payload.value, payload.note, created_at.isoformat()),
        )
    return FeedbackResponse(
        id=cursor.lastrowid,
        offer_id=offer_id,
        value=payload.value,
        note=payload.note,
        created_at=created_at,
    )


@router.get(
    "/api/insights/market", response_model=MarketInsightsResponse, tags=["insights"]
)
def market_insights(
    store: Annotated[RadarStore, Depends(_store)],
) -> MarketInsightsResponse:
    offers = store.list_scored_offers(active_only=True)
    decisions = Counter(offer.decision for offer in offers)
    skills = Counter(
        fact.value for offer in offers for fact in offer.facts if fact.name == "skill"
    )
    return MarketInsightsResponse(
        total_offers=len(offers),
        decisions=dict(sorted(decisions.items())),
        skills=[
            {"name": name, "count": count}
            for name, count in sorted(
                skills.items(), key=lambda item: (-item[1], item[0])
            )
        ],
    )


@router.get("/api/sources", response_model=list[SourceResponse], tags=["sources"])
def list_sources(
    request: Request,
    store: Annotated[RadarStore, Depends(_store)],
) -> list[SourceResponse]:
    config = _config(request)
    store.repair_legacy_data()
    with _connect(store) as connection:
        health_rows = {
            normalize_source_key(row["source"]): row
            for row in connection.execute("SELECT * FROM source_health").fetchall()
        }
        stored_names = {
            normalize_source_key(row["source"])
            for row in connection.execute(
                "SELECT DISTINCT source FROM offer_sources"
            ).fetchall()
        }
    result = []
    source_names = set(config.sources.sources) | stored_names | set(health_rows)
    for name in sorted(source_names):
        source = config.sources.sources.get(name)
        health_row = health_rows.get(name)
        available = bool(source and remote_connector_available(name, source.mode))
        result.append(
            SourceResponse(
                name=name,
                mode=source.mode if source else "stored",
                enabled=source.enabled if source else False,
                available=available,
                automated=bool(source and source.enabled and available),
                quota_per_day=source.quota_per_day if source else 0,
                credential_configured=(
                    not source.api_key_env or bool(os.environ.get(source.api_key_env))
                    if source
                    else True
                ),
                health_status=health_row["status"] if health_row else "not_run",
                last_success_at=health_row["last_success_at"] if health_row else None,
                quota_remaining=health_row["quota_remaining"] if health_row else None,
            )
        )
    return result


@router.post(
    "/api/refresh",
    response_model=RefreshResponse,
    dependencies=[Depends(require_session)],
    tags=["refresh"],
)
def refresh(
    payload: RefreshRequest,
    request: Request,
    store: Annotated[RadarStore, Depends(_store)],
) -> RefreshResponse:
    config = _config(request)
    sources = payload.sources or [
        name
        for name, source in config.sources.sources.items()
        if source.enabled and source.mode != "manual_only"
    ]
    try:
        return refresh_store(store, config, sources)
    except RefreshPolicyFailure as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    except RefreshExecutionError as error:
        raise HTTPException(status_code=500, detail=str(error)) from None


@router.get(
    "/api/refresh/status",
    response_model=list[RefreshStatusResponse],
    tags=["refresh"],
)
def refresh_status(
    store: Annotated[RadarStore, Depends(_store)],
) -> list[dict[str, object]]:
    with _connect(store) as connection:
        rows = connection.execute(
            "SELECT * FROM refresh_runs ORDER BY started_at DESC, id DESC LIMIT 50"
        ).fetchall()
    return [dict(row) for row in rows]


@router.get(
    "/api/saved-views", response_model=list[SavedViewResponse], tags=["saved-views"]
)
def list_saved_views(
    store: Annotated[RadarStore, Depends(_store)],
) -> list[dict[str, object]]:
    with _connect(store) as connection:
        rows = connection.execute(
            "SELECT * FROM saved_views ORDER BY name, id"
        ).fetchall()
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "filters": json.loads(row["filters_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


@router.post(
    "/api/saved-views",
    response_model=SavedViewResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_session)],
    tags=["saved-views"],
)
def create_saved_view(
    payload: SavedViewRequest,
    store: Annotated[RadarStore, Depends(_store)],
) -> dict[str, object]:
    now = _utc_now().isoformat()
    try:
        with _connect(store) as connection:
            cursor = connection.execute(
                "INSERT INTO saved_views (name, filters_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (payload.name, json.dumps(payload.filters, sort_keys=True), now, now),
            )
    except sqlite3.IntegrityError as error:
        raise HTTPException(
            status_code=409, detail="Saved view name already exists"
        ) from error
    return {
        "id": cursor.lastrowid,
        "name": payload.name,
        "filters": payload.filters,
        "created_at": now,
        "updated_at": now,
    }


@router.put(
    "/api/saved-views/{view_id}",
    response_model=SavedViewResponse,
    dependencies=[Depends(require_session)],
    tags=["saved-views"],
)
def update_saved_view(
    view_id: int,
    payload: SavedViewRequest,
    store: Annotated[RadarStore, Depends(_store)],
) -> dict[str, object]:
    now = _utc_now().isoformat()
    try:
        with _connect(store) as connection:
            cursor = connection.execute(
                "UPDATE saved_views SET name = ?, filters_json = ?, updated_at = ? WHERE id = ?",
                (
                    payload.name,
                    json.dumps(payload.filters, sort_keys=True),
                    now,
                    view_id,
                ),
            )
            row = connection.execute(
                "SELECT created_at FROM saved_views WHERE id = ?", (view_id,)
            ).fetchone()
    except sqlite3.IntegrityError as error:
        raise HTTPException(
            status_code=409, detail="Saved view name already exists"
        ) from error
    if cursor.rowcount == 0 or row is None:
        raise HTTPException(status_code=404, detail="Saved view not found")
    return {
        "id": view_id,
        "name": payload.name,
        "filters": payload.filters,
        "created_at": row["created_at"],
        "updated_at": now,
    }


@router.delete(
    "/api/saved-views/{view_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_session)],
    tags=["saved-views"],
)
def delete_saved_view(
    view_id: int,
    store: Annotated[RadarStore, Depends(_store)],
) -> Response:
    with _connect(store) as connection:
        cursor = connection.execute("DELETE FROM saved_views WHERE id = ?", (view_id,))
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Saved view not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/api/config",
    response_model=AppConfig,
    dependencies=[Depends(require_loopback)],
    tags=["configuration"],
)
def read_config(request: Request) -> AppConfig:
    return _config(request)


@router.post(
    "/api/config/validate",
    response_model=ConfigValidationResponse,
    tags=["configuration"],
)
def validate_config(payload: dict[str, object]) -> ConfigValidationResponse:
    try:
        AppConfig.model_validate(payload)
    except ValidationError as error:
        return ConfigValidationResponse(valid=False, errors=_validation_issues(error))
    return ConfigValidationResponse(valid=True, errors=[])


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_exclusive_file(path: Path, payload: bytes, *, mode: int = 0o600) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, mode)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)


def _write_config(config_dir: Path, config: AppConfig) -> None:
    generations = config_dir / GENERATIONS_DIRECTORY
    try:
        ensure_private_directory(config_dir)
        ensure_private_directory(generations)
    except PrivatePathError as error:
        raise ConfigWriteError("Configuration update failed") from error

    document = config.model_dump(mode="json")
    generation_id = secrets.token_hex(16)
    generation = generations / generation_id
    pointer = config_dir / ACTIVE_GENERATION_POINTER
    pointer_temporary = config_dir / (
        f".{ACTIVE_GENERATION_POINTER}.{secrets.token_hex(12)}.tmp"
    )
    switched = False
    try:
        generation.mkdir(mode=0o700)
        for filename in EXAMPLE_FILENAMES:
            payload = yaml.safe_dump(
                document[filename.removesuffix(".yml")],
                sort_keys=False,
                allow_unicode=False,
            ).encode()
            destination = generation / filename
            _write_exclusive_file(destination, payload)
            destination.chmod(0o600, follow_symlinks=False)
        _fsync_directory(generation)
        generation.chmod(0o700, follow_symlinks=False)
        _fsync_directory(generations)

        try:
            pointer_stat = pointer.lstat()
        except FileNotFoundError:
            pass
        else:
            if stat.S_ISLNK(pointer_stat.st_mode) or not stat.S_ISREG(
                pointer_stat.st_mode
            ):
                raise ConfigWriteError("Configuration update failed")
        _write_exclusive_file(pointer_temporary, f"{generation_id}\n".encode())
        os.replace(pointer_temporary, pointer)
        switched = True
        pointer.chmod(0o600, follow_symlinks=False)
        _fsync_directory(config_dir)
    except Exception as error:
        if not switched:
            with suppress(OSError):
                generation.chmod(0o700, follow_symlinks=False)
            with suppress(OSError):
                shutil.rmtree(generation)
        raise ConfigWriteError("Configuration update failed") from error
    finally:
        with suppress(OSError):
            pointer_temporary.unlink()


@router.put(
    "/api/config",
    response_model=AppConfig,
    dependencies=[Depends(require_session)],
    tags=["configuration"],
)
def write_config(payload: dict[str, object], request: Request) -> AppConfig:
    try:
        config = AppConfig.model_validate(payload)
    except ValidationError as error:
        raise HTTPException(
            status_code=422, detail=_validation_issues(error)
        ) from error
    try:
        _write_config(_config_dir(request), config)
    except ConfigWriteError:
        raise HTTPException(
            status_code=500, detail="Configuration update failed"
        ) from None
    return config


@router.post(
    "/api/rescore",
    response_model=RescoreResponse,
    dependencies=[Depends(require_session)],
    tags=["offers"],
)
def rescore(
    request: Request,
    store: Annotated[RadarStore, Depends(_store)],
) -> RescoreResponse:
    return rescore_store(store, _config(request))
