"""Small transactional SQLite repository for the local radar."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from job_radar.config.models import normalize_source_key
from job_radar.db.migrations import (
    has_public_schema,
    migrate,
    repair_legacy_provenance,
    repair_legacy_source_health,
)
from job_radar.local_security import (
    create_or_validate_private_file,
    ensure_private_directory,
)
from job_radar.models import OfferFact, RawOffer, ScoreBreakdown, ScoredOffer

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


class RadarStore:
    """Persist materialized offers without coupling storage to the scoring pipeline."""

    def __init__(self, path: Path) -> None:
        self.path = path
        uses_existing_cwd = not self.path.is_absolute() and self.path.parent == Path(".")
        if not uses_existing_cwd:
            ensure_private_directory(self.path.parent)
        create_or_validate_private_file(self.path)
        with self._connect() as connection:
            if has_public_schema(connection):
                migrate(connection)
            connection.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
            repair_legacy_provenance(connection)
            repair_legacy_source_health(connection)

    def repair_legacy_data(self) -> None:
        """Apply idempotent compatibility repairs before bulk reads."""

        with self._connect() as connection:
            repair_legacy_provenance(connection)
            repair_legacy_source_health(connection)

    def table_names(self) -> set[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
            return {row["name"] for row in rows}

    def save_scored_offer(
        self,
        scored: ScoredOffer,
        *,
        processed_at: datetime,
        profile_id: str = "default",
        canonical_key: str | None = None,
        reactivate: bool = True,
    ) -> None:
        """Replace one materialized offer atomically, including its facts and score."""

        self.save_scored_batch(
            [scored],
            canonical_keys=[canonical_key or self._fingerprint(scored.offer)],
            processed_at=processed_at,
            profile_id=profile_id,
            reactivate=reactivate,
        )

    def save_scored_batch(
        self,
        scored_offers: Sequence[ScoredOffer],
        *,
        canonical_keys: Sequence[str],
        processed_at: datetime,
        profile_id: str = "default",
        reactivate: bool = True,
    ) -> None:
        """Materialize a reconciled batch in one all-or-nothing transaction."""

        if len(scored_offers) != len(canonical_keys):
            raise ValueError("canonical_keys must contain one key per scored offer")
        if any(not key.strip() for key in canonical_keys):
            raise ValueError("canonical keys must not be empty")
        processing_time = self._timestamp(processed_at)
        with self._connect() as connection:
            for scored, key in zip(scored_offers, canonical_keys, strict=True):
                self._save_scored_offer(
                    connection,
                    scored,
                    canonical_key=key,
                    processing_time=processing_time,
                    profile_id=profile_id,
                    reactivate=reactivate,
                )
            connection.execute(
                "DELETE FROM offers WHERE NOT EXISTS "
                "(SELECT 1 FROM offer_sources WHERE offer_sources.offer_id = offers.id)"
            )

    def provenance_canonical_keys(self) -> dict[tuple[str, str], str]:
        """Return stable source identities mapped to their existing canonical offer."""

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT os.source, os.external_id, o.canonical_key "
                "FROM offer_sources AS os "
                "JOIN offers AS o ON o.id = os.offer_id "
                "ORDER BY os.source, os.external_id"
            ).fetchall()
        return {
            (normalize_source_key(row["source"]), row["external_id"].strip()): row[
                "canonical_key"
            ]
            for row in rows
        }

    def _save_scored_offer(
        self,
        connection: sqlite3.Connection,
        scored: ScoredOffer,
        *,
        canonical_key: str,
        processing_time: str,
        profile_id: str,
        reactivate: bool,
    ) -> None:
        if scored.relevance != sum(axis.points for axis in scored.axes):
            raise ValueError("relevance must equal the sum of axis points")

        offer = scored.offer
        fingerprint = self._fingerprint(offer)
        published_at = self._timestamp(offer.published_at)
        raw_payload = json.dumps(offer.model_dump(mode="json"), sort_keys=True)
        existing = connection.execute(
            "SELECT o.canonical_key FROM offer_sources AS os "
            "JOIN offers AS o ON o.id = os.offer_id "
            "WHERE os.source = ? AND os.external_id = ?",
            (normalize_source_key(offer.source), offer.external_id.strip()),
        ).fetchone()
        if existing is not None:
            canonical_key = existing["canonical_key"]
        connection.execute(
            """
            INSERT INTO offers (
                canonical_key, title, company, location, contract, remote, description, published_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(canonical_key) DO UPDATE SET
                title = excluded.title,
                company = excluded.company,
                location = excluded.location,
                contract = excluded.contract,
                remote = excluded.remote,
                description = excluded.description,
                published_at = excluded.published_at,
                status = CASE WHEN ? THEN 'active' ELSE offers.status END
            """,
            (
                canonical_key,
                offer.title,
                offer.company,
                offer.location,
                offer.contract,
                offer.remote,
                offer.description,
                published_at,
                reactivate,
            ),
        )
        offer_id = connection.execute(
            "SELECT id FROM offers WHERE canonical_key = ?", (canonical_key,)
        ).fetchone()["id"]
        connection.execute(
            """
            INSERT INTO offer_sources (
                offer_id, source, external_id, source_url, fingerprint, first_seen_at,
                last_seen_at, raw_payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, external_id) DO UPDATE SET
                offer_id = excluded.offer_id,
                source_url = excluded.source_url,
                fingerprint = excluded.fingerprint,
                last_seen_at = excluded.last_seen_at,
                raw_payload_json = excluded.raw_payload_json
            """,
            (
                offer_id,
                offer.source,
                offer.external_id,
                offer.url,
                fingerprint,
                processing_time,
                processing_time,
                raw_payload,
            ),
        )
        connection.execute(
            "DELETE FROM offer_facts WHERE source_fingerprint = ?",
            (fingerprint,),
        )
        connection.executemany(
            """
            INSERT INTO offer_facts (
                offer_id, source_fingerprint, name, value, citation, confidence,
                extracted_at, facts_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    offer_id,
                    fingerprint,
                    fact.name,
                    fact.value,
                    fact.citation,
                    fact.confidence,
                    processing_time,
                    scored.score_version,
                )
                for fact in scored.facts
            ],
        )
        connection.execute(
            """
            INSERT INTO offer_scores (
                offer_id, source_fingerprint, profile_id, relevance, confidence,
                freshness_days, decision, blocker, axes_json, score_version, scored_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(offer_id, source_fingerprint, profile_id) DO UPDATE SET
                relevance = excluded.relevance,
                confidence = excluded.confidence,
                freshness_days = excluded.freshness_days,
                decision = excluded.decision,
                blocker = excluded.blocker,
                axes_json = excluded.axes_json,
                score_version = excluded.score_version,
                scored_at = excluded.scored_at
            """,
            (
                offer_id,
                fingerprint,
                profile_id,
                scored.relevance,
                scored.confidence,
                scored.freshness_days,
                scored.decision,
                scored.blocker,
                json.dumps([axis.model_dump() for axis in scored.axes], sort_keys=True),
                scored.score_version,
                processing_time,
            ),
        )

    def get_scored_offer(
        self, source: str, external_id: str, *, profile_id: str = "default"
    ) -> ScoredOffer:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT o.*, os.source, os.external_id, os.source_url, os.raw_payload_json,
                       os.fingerprint AS source_fingerprint, s.relevance, s.confidence,
                       s.freshness_days, s.decision, s.blocker, s.axes_json, s.score_version
                FROM offers AS o
                JOIN offer_sources AS os ON os.offer_id = o.id
                JOIN offer_scores AS s
                  ON s.offer_id = o.id AND s.source_fingerprint = os.fingerprint
                WHERE os.source = ? AND os.external_id = ? AND s.profile_id = ?
                  AND json_extract(
                      os.raw_payload_json, '$._quarantine_reason'
                  ) IS NULL
                """,
                (normalize_source_key(source), external_id.strip(), profile_id),
            ).fetchone()
            if row is None:
                raise KeyError(f"offer not found: {source}:{external_id}")
            facts = connection.execute(
                """
                SELECT name, value, citation, confidence
                FROM offer_facts
                WHERE offer_id = ? AND source_fingerprint = ?
                ORDER BY id
                """,
                (row["id"], row["source_fingerprint"]),
            ).fetchall()
        return self._to_scored_offer(row, facts)

    def list_scored_offers(
        self, *, profile_id: str = "default", active_only: bool = False
    ) -> list[ScoredOffer]:
        with self._connect() as connection:
            rows = self._ranked_rows(connection, profile_id, active_only=active_only)
            facts_by_provenance = {
                (row["offer_id"], row["source_fingerprint"]): []
                for row in connection.execute(
                    "SELECT DISTINCT offer_id, source_fingerprint FROM offer_facts"
                ).fetchall()
            }
            for fact in connection.execute(
                """
                SELECT offer_id, source_fingerprint, name, value, citation, confidence
                FROM offer_facts
                ORDER BY id
                """
            ):
                key = (fact["offer_id"], fact["source_fingerprint"])
                facts_by_provenance.setdefault(key, []).append(
                    {
                        "name": fact["name"],
                        "value": fact["value"],
                        "citation": fact["citation"],
                        "confidence": fact["confidence"],
                    }
                )
        return [
            self._to_scored_offer(
                row,
                facts_by_provenance.get((row["id"], row["source_fingerprint"]), []),
            )
            for row in rows
        ]

    def list_canonical_offers(
        self, *, profile_id: str = "default"
    ) -> list[tuple[str, RawOffer]]:
        """Return one deterministic source representation per canonical offer."""

        with self._connect() as connection:
            rows = self._ranked_rows(connection, profile_id)
        return [(row["canonical_key"], self._raw_offer(row)) for row in rows]

    def list_provenance(self, source: str, external_id: str) -> list[dict[str, str]]:
        """List every source record attached to the selected canonical offer."""

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT sibling.source, sibling.external_id, sibling.source_url
                FROM offer_sources AS selected
                JOIN offer_sources AS sibling ON sibling.offer_id = selected.offer_id
                WHERE selected.source = ? AND selected.external_id = ?
                  AND json_extract(
                      selected.raw_payload_json, '$._quarantine_reason'
                  ) IS NULL
                  AND json_extract(
                      sibling.raw_payload_json, '$._quarantine_reason'
                  ) IS NULL
                ORDER BY sibling.source, sibling.external_id
                """,
                (normalize_source_key(source), external_id.strip()),
            ).fetchall()
        if not rows:
            raise KeyError(f"offer not found: {source}:{external_id}")
        return [
            {
                "source": row["source"],
                "external_id": row["external_id"],
                "url": row["source_url"],
            }
            for row in rows
        ]

    @staticmethod
    def _ranked_rows(
        connection: sqlite3.Connection,
        profile_id: str,
        *,
        active_only: bool = False,
    ) -> list[sqlite3.Row]:
        return connection.execute(
            """
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
                        ORDER BY
                            s.confidence DESC,
                            s.relevance DESC,
                            os.source ASC,
                            os.external_id ASC
                    ) AS provenance_rank
                FROM offer_sources AS os
                JOIN offer_scores AS s
                  ON s.offer_id = os.offer_id
                 AND s.source_fingerprint = os.fingerprint
                WHERE s.profile_id = ?
                  AND json_extract(
                      os.raw_payload_json, '$._quarantine_reason'
                  ) IS NULL
            )
            SELECT o.*, ranked.*
            FROM offers AS o
            JOIN ranked ON ranked.offer_id = o.id
            WHERE ranked.provenance_rank = 1
              AND (? = 0 OR o.status = 'active')
            ORDER BY o.canonical_key
            """,
            (profile_id, int(active_only)),
        ).fetchall()

    def offer_fingerprints(self) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT fingerprint FROM offer_sources ORDER BY fingerprint"
            ).fetchall()
            return [row["fingerprint"] for row in rows]

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _fingerprint(offer: RawOffer) -> str:
        return json.dumps(
            (offer.source, offer.external_id),
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @staticmethod
    def _timestamp(value) -> str:
        if value.tzinfo is None:
            raise ValueError("timestamps must include a timezone")
        return value.astimezone(UTC).isoformat()

    @staticmethod
    def _raw_offer(row: sqlite3.Row) -> RawOffer:
        payload = json.loads(row["raw_payload_json"])
        if payload:
            return RawOffer.model_validate(payload)
        return RawOffer(
            external_id=row["external_id"],
            source=row["source"],
            url=row["source_url"],
            title=row["title"],
            company=row["company"],
            location=row["location"],
            contract=row["contract"],
            remote=row["remote"],
            description=row["description"],
            published_at=row["published_at"],
        )

    @staticmethod
    def _to_scored_offer(
        row: sqlite3.Row, facts: list[sqlite3.Row | dict[str, object]]
    ) -> ScoredOffer:
        return ScoredOffer(
            offer=RadarStore._raw_offer(row),
            facts=[OfferFact.model_validate(dict(fact)) for fact in facts],
            axes=[
                ScoreBreakdown.model_validate(axis)
                for axis in json.loads(row["axes_json"])
            ],
            relevance=row["relevance"],
            confidence=row["confidence"],
            freshness_days=row["freshness_days"],
            decision=row["decision"],
            score_version=row["score_version"],
            blocker=row["blocker"],
        )
