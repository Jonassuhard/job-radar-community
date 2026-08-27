"""Versioned, transactional migrations for the local SQLite database."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

from pydantic import ValidationError

from job_radar.config.models import normalize_source_key
from job_radar.models import RawOffer

CURRENT_SCHEMA_VERSION = 2
PUBLIC_TABLE_NAMES = frozenset(
    {
        "http_cache",
        "offer_facts",
        "offer_scores",
        "offer_sources",
        "offers",
        "refresh_runs",
        "saved_views",
        "source_health",
        "user_feedback",
    }
)


_CREATE_FACTS_V2 = """
CREATE TABLE offer_facts (
    id INTEGER PRIMARY KEY,
    offer_id INTEGER NOT NULL REFERENCES offers(id) ON DELETE CASCADE,
    source_fingerprint TEXT NOT NULL,
    name TEXT NOT NULL,
    value TEXT NOT NULL,
    citation TEXT NOT NULL,
    confidence INTEGER NOT NULL CHECK(confidence BETWEEN 0 AND 100),
    extracted_at TEXT NOT NULL,
    facts_version TEXT NOT NULL,
    UNIQUE(offer_id, source_fingerprint, name, value, citation),
    FOREIGN KEY (offer_id, source_fingerprint)
        REFERENCES offer_sources(offer_id, fingerprint)
        ON DELETE CASCADE ON UPDATE CASCADE
)
"""

_CREATE_SCORES_V2 = """
CREATE TABLE offer_scores (
    offer_id INTEGER NOT NULL REFERENCES offers(id) ON DELETE CASCADE,
    source_fingerprint TEXT NOT NULL,
    profile_id TEXT NOT NULL DEFAULT 'default',
    relevance INTEGER NOT NULL CHECK(relevance BETWEEN 0 AND 100),
    confidence INTEGER NOT NULL CHECK(confidence BETWEEN 0 AND 100),
    freshness_days INTEGER NOT NULL CHECK(freshness_days >= 0),
    decision TEXT NOT NULL,
    blocker TEXT,
    axes_json TEXT NOT NULL,
    score_version TEXT NOT NULL,
    scored_at TEXT NOT NULL,
    PRIMARY KEY (offer_id, source_fingerprint, profile_id),
    FOREIGN KEY (offer_id, source_fingerprint)
        REFERENCES offer_sources(offer_id, fingerprint)
        ON DELETE CASCADE ON UPDATE CASCADE
)
"""


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}


def has_public_schema(connection: sqlite3.Connection) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'offers'"
    ).fetchone()
    return row is not None


def migrate(connection: sqlite3.Connection) -> None:
    """Bring an existing Task 3 or intermediate database to the current schema."""

    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version > CURRENT_SCHEMA_VERSION:
        raise RuntimeError(
            f"database schema version {version} is newer than supported "
            f"version {CURRENT_SCHEMA_VERSION}"
        )
    if version == CURRENT_SCHEMA_VERSION:
        return

    connection.execute("BEGIN IMMEDIATE")
    try:
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_offer_sources_offer_fingerprint "
            "ON offer_sources(offer_id, fingerprint)"
        )
        _populate_raw_payloads(connection)
        _rebuild_facts(connection)
        _rebuild_scores(connection)
        connection.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise sqlite3.IntegrityError(
                f"foreign key check failed with {len(violations)} violation(s)"
            )
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise sqlite3.DatabaseError(f"integrity check failed: {integrity}")
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def repair_legacy_provenance(connection: sqlite3.Connection) -> None:
    """Normalize historical identities and quarantine payloads unsafe to expose."""

    if "raw_payload_json" not in _columns(connection, "offer_sources"):
        return
    connection.execute("SAVEPOINT repair_legacy_provenance")
    try:
        rows = connection.execute(
            "SELECT id, source, external_id, source_url, fingerprint, raw_payload_json "
            "FROM offer_sources ORDER BY id"
        ).fetchall()
        for row in rows:
            source_id, source, external_id, source_url, fingerprint, raw_payload = row
            normalized_source = normalize_source_key(source)
            normalized_external_id = external_id.strip()
            normalized_fingerprint = json.dumps(
                (normalized_source, normalized_external_id),
                ensure_ascii=False,
                separators=(",", ":"),
            )
            normalized_payload, safe_url = _repair_raw_payload(
                raw_payload,
                source=normalized_source,
                external_id=normalized_external_id,
                source_url=source_url,
            )
            collision = connection.execute(
                "SELECT id FROM offer_sources "
                "WHERE source = ? AND external_id = ? AND id <> ? LIMIT 1",
                (normalized_source, normalized_external_id, source_id),
            ).fetchone()
            if collision is not None:
                payload = json.loads(normalized_payload)
                payload["_quarantine_reason"] = "normalized_identity_collision"
                connection.execute(
                    "UPDATE offer_sources SET source_url = '', raw_payload_json = ? "
                    "WHERE id = ?",
                    (json.dumps(payload, ensure_ascii=False, sort_keys=True), source_id),
                )
                continue
            if (
                source == normalized_source
                and external_id == normalized_external_id
                and fingerprint == normalized_fingerprint
                and source_url == safe_url
                and raw_payload == normalized_payload
            ):
                continue
            connection.execute(
                "UPDATE offer_sources SET source = ?, external_id = ?, source_url = ?, "
                "fingerprint = ?, raw_payload_json = ? WHERE id = ?",
                (
                    normalized_source,
                    normalized_external_id,
                    safe_url,
                    normalized_fingerprint,
                    normalized_payload,
                    source_id,
                ),
            )
        connection.execute("RELEASE SAVEPOINT repair_legacy_provenance")
    except Exception:
        connection.execute("ROLLBACK TO SAVEPOINT repair_legacy_provenance")
        connection.execute("RELEASE SAVEPOINT repair_legacy_provenance")
        raise


def repair_legacy_source_health(connection: sqlite3.Connection) -> None:
    """Merge case/Unicode variants while retaining the freshest health evidence."""

    if not _columns(connection, "source_health"):
        return
    connection.execute("SAVEPOINT repair_legacy_source_health")
    try:
        rows = connection.execute(
            "SELECT source, status, last_success_at, quota_remaining, updated_at "
            "FROM source_health ORDER BY source"
        ).fetchall()
        groups: dict[str, list[tuple[object, ...]]] = {}
        for row in rows:
            normalized = normalize_source_key(row[0]) or row[0]
            groups.setdefault(normalized, []).append(tuple(row))
        for normalized, variants in groups.items():
            freshest = max(
                variants,
                key=lambda row: (
                    _timestamp_sort_key(row[4]),
                    row[0] == normalized,
                    row[0],
                ),
            )
            successes = [row[2] for row in variants if row[2] is not None]
            latest_success = (
                max(successes, key=_timestamp_sort_key) if successes else None
            )
            merged = (
                normalized,
                freshest[1],
                latest_success,
                freshest[3],
                freshest[4],
            )
            if len(variants) == 1 and variants[0] == merged:
                continue
            connection.executemany(
                "DELETE FROM source_health WHERE source = ?",
                [(row[0],) for row in variants],
            )
            connection.execute(
                "INSERT INTO source_health "
                "(source, status, last_success_at, quota_remaining, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                merged,
            )
        connection.execute("RELEASE SAVEPOINT repair_legacy_source_health")
    except Exception:
        connection.execute("ROLLBACK TO SAVEPOINT repair_legacy_source_health")
        connection.execute("RELEASE SAVEPOINT repair_legacy_source_health")
        raise


def _timestamp_sort_key(value: object) -> tuple[int, float, str]:
    if not isinstance(value, str):
        return (0, float("-inf"), "")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return (0, float("-inf"), value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return (1, parsed.astimezone(UTC).timestamp(), value)


def _repair_raw_payload(
    raw_payload: str,
    *,
    source: str,
    external_id: str,
    source_url: str,
) -> tuple[str, str]:
    try:
        payload = json.loads(raw_payload)
    except (TypeError, json.JSONDecodeError):
        payload = {
            "_quarantine_reason": "invalid_raw_offer",
            "_quarantined_raw_payload": raw_payload,
        }
    if not isinstance(payload, dict):
        payload = {
            "_quarantine_reason": "invalid_raw_offer",
            "_quarantined_raw_payload": payload,
        }
    payload["source"] = source
    payload["external_id"] = external_id
    if "_quarantine_reason" in payload:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True), ""
    try:
        validated = RawOffer.model_validate(payload)
    except ValidationError as error:
        url_is_invalid = any(detail["loc"] == ("url",) for detail in error.errors())
        payload["_quarantine_reason"] = (
            "invalid_url" if url_is_invalid else "invalid_raw_offer"
        )
        if url_is_invalid:
            payload["_quarantined_url"] = payload.get("url", source_url)
            payload["url"] = ""
        return json.dumps(payload, ensure_ascii=False, sort_keys=True), ""
    normalized_payload = json.dumps(
        validated.model_dump(mode="json"), ensure_ascii=False, sort_keys=True
    )
    return normalized_payload, validated.url


def _populate_raw_payloads(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        """
        SELECT
            os.id,
            os.source,
            os.external_id,
            os.source_url,
            os.raw_payload_json,
            o.title,
            o.company,
            o.location,
            o.contract,
            o.remote,
            o.description,
            o.published_at
        FROM offer_sources AS os
        JOIN offers AS o ON o.id = os.offer_id
        ORDER BY os.id
        """
    ).fetchall()
    updates = []
    for row in rows:
        if row[4] not in {"", "{}"}:
            continue
        payload = {
            "external_id": row[2],
            "source": row[1],
            "url": row[3],
            "title": row[5],
            "company": row[6],
            "location": row[7],
            "contract": row[8],
            "remote": row[9],
            "description": row[10],
            "published_at": row[11],
        }
        updates.append((json.dumps(payload, sort_keys=True), row[0]))
    connection.executemany(
        "UPDATE offer_sources SET raw_payload_json = ? WHERE id = ?", updates
    )


def _rebuild_facts(connection: sqlite3.Connection) -> None:
    has_fingerprint = "source_fingerprint" in _columns(connection, "offer_facts")
    connection.execute("ALTER TABLE offer_facts RENAME TO offer_facts_legacy")
    connection.execute(_CREATE_FACTS_V2)
    if has_fingerprint:
        source_selector = """
            COALESCE(
                (
                    SELECT exact.fingerprint
                    FROM offer_sources AS exact
                    WHERE exact.offer_id = legacy.offer_id
                      AND exact.fingerprint = legacy.source_fingerprint
                    LIMIT 1
                ),
                (
                    SELECT stable.fingerprint
                    FROM offer_sources AS stable
                    WHERE stable.offer_id = legacy.offer_id
                    ORDER BY stable.source, stable.external_id, stable.id
                    LIMIT 1
                )
            )
        """
    else:
        source_selector = """
            (
                SELECT stable.fingerprint
                FROM offer_sources AS stable
                WHERE stable.offer_id = legacy.offer_id
                ORDER BY stable.source, stable.external_id, stable.id
                LIMIT 1
            )
        """
    connection.execute(
        f"""
        INSERT INTO offer_facts (
            id, offer_id, source_fingerprint, name, value, citation, confidence,
            extracted_at, facts_version
        )
        SELECT
            legacy.id,
            legacy.offer_id,
            {source_selector},
            legacy.name,
            legacy.value,
            legacy.citation,
            legacy.confidence,
            legacy.extracted_at,
            legacy.facts_version
        FROM offer_facts_legacy AS legacy
        """
    )
    connection.execute("DROP TABLE offer_facts_legacy")
    connection.execute("CREATE INDEX idx_offer_facts_offer_id ON offer_facts(offer_id)")
    connection.execute(
        "CREATE INDEX idx_offer_facts_name_value ON offer_facts(name, value)"
    )
    connection.execute(
        "CREATE INDEX idx_offer_facts_provenance ON offer_facts(source_fingerprint)"
    )


def _rebuild_scores(connection: sqlite3.Connection) -> None:
    has_fingerprint = "source_fingerprint" in _columns(connection, "offer_scores")
    connection.execute("ALTER TABLE offer_scores RENAME TO offer_scores_legacy")
    connection.execute(_CREATE_SCORES_V2)
    if has_fingerprint:
        source_selector = """
            COALESCE(
                (
                    SELECT exact.fingerprint
                    FROM offer_sources AS exact
                    WHERE exact.offer_id = legacy.offer_id
                      AND exact.fingerprint = legacy.source_fingerprint
                    LIMIT 1
                ),
                (
                    SELECT stable.fingerprint
                    FROM offer_sources AS stable
                    WHERE stable.offer_id = legacy.offer_id
                    ORDER BY stable.source, stable.external_id, stable.id
                    LIMIT 1
                )
            )
        """
    else:
        source_selector = """
            (
                SELECT stable.fingerprint
                FROM offer_sources AS stable
                WHERE stable.offer_id = legacy.offer_id
                ORDER BY stable.source, stable.external_id, stable.id
                LIMIT 1
            )
        """
    connection.execute(
        f"""
        INSERT INTO offer_scores (
            offer_id, source_fingerprint, profile_id, relevance, confidence,
            freshness_days, decision, blocker, axes_json, score_version, scored_at
        )
        SELECT
            legacy.offer_id,
            {source_selector},
            legacy.profile_id,
            legacy.relevance,
            legacy.confidence,
            legacy.freshness_days,
            legacy.decision,
            legacy.blocker,
            legacy.axes_json,
            legacy.score_version,
            legacy.scored_at
        FROM offer_scores_legacy AS legacy
        """
    )
    connection.execute("DROP TABLE offer_scores_legacy")
    connection.execute(
        "CREATE INDEX idx_offer_scores_decision_rank "
        "ON offer_scores(decision, relevance DESC)"
    )
    connection.execute(
        "CREATE INDEX idx_offer_scores_profile_rank "
        "ON offer_scores(profile_id, relevance DESC)"
    )
