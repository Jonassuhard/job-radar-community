from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from job_radar.db.store import RadarStore
from job_radar.models import OfferFact, RawOffer, ScoreBreakdown, ScoredOffer

FIXED_NOW = datetime(2026, 8, 26, 9, 30, tzinfo=UTC)
LEGACY_SCHEMA = Path(__file__).with_name("task3_schema.sql")


def _create_task3_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(LEGACY_SCHEMA.read_text(encoding="utf-8"))
        connection.execute(
            """
            INSERT INTO offers (
                id, canonical_key, title, company, location, contract, remote,
                description, published_at
            ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "public_ats:legacy-001",
                "Product Operations Analyst",
                "Northstar Works",
                "Paris",
                "permanent",
                "hybrid",
                "Coordinate legacy analytics.",
                FIXED_NOW.isoformat(),
            ),
        )
        connection.execute(
            """
            INSERT INTO offer_sources (
                offer_id, source, external_id, source_url, fingerprint,
                first_seen_at, last_seen_at
            ) VALUES (1, ?, ?, ?, ?, ?, ?)
            """,
            (
                "public_ats",
                "legacy-001",
                "https://legacy.example/jobs/legacy-001",
                "public_ats:legacy-001",
                FIXED_NOW.isoformat(),
                FIXED_NOW.isoformat(),
            ),
        )
        connection.execute(
            """
            INSERT INTO offer_facts (
                offer_id, name, value, citation, confidence, extracted_at, facts_version
            ) VALUES (1, 'skill', 'analytics', 'legacy analytics', 88, ?, 'legacy-v1')
            """,
            (FIXED_NOW.isoformat(),),
        )
        connection.execute(
            """
            INSERT INTO offer_scores (
                offer_id, profile_id, relevance, confidence, freshness_days, decision,
                blocker, axes_json, score_version, scored_at
            ) VALUES (1, 'default', 70, 88, 0, 'recommended', NULL, ?, 'legacy-v1', ?)
            """,
            (
                json.dumps(
                    [{"name": "role", "points": 70, "explanation": "Legacy match."}]
                ),
                FIXED_NOW.isoformat(),
            ),
        )
    path.chmod(0o600)


def _second_provenance() -> ScoredOffer:
    return ScoredOffer(
        offer=RawOffer(
            external_id="api-002",
            source="second_api",
            url="https://api.example/jobs/api-002",
            title="Product Operations Analyst",
            company="Northstar Works",
            location="Paris",
            contract="permanent",
            remote="hybrid",
            description="A second API cites workflow governance.",
            published_at=FIXED_NOW,
        ),
        facts=[
            OfferFact(
                name="skill",
                value="workflow governance",
                citation="workflow governance",
                confidence=96,
            )
        ],
        axes=[ScoreBreakdown(name="role", points=80, explanation="API match.")],
        relevance=80,
        confidence=96,
        freshness_days=0,
        decision="priority",
        score_version="config-v2",
    )


def test_task3_database_migrates_transactionally_then_reads_and_writes(tmp_path):
    path = tmp_path / "legacy.db"
    _create_task3_database(path)

    store = RadarStore(path)

    legacy = store.get_scored_offer("public_ats", "legacy-001")
    assert legacy.relevance == 70
    assert legacy.facts[0].citation == "legacy analytics"

    store.save_scored_offer(
        _second_provenance(),
        processed_at=FIXED_NOW,
        canonical_key="public_ats:legacy-001",
    )

    assert store.get_scored_offer("public_ats", "legacy-001").relevance == 70
    assert store.get_scored_offer("second_api", "api-002").relevance == 80
    assert store.list_scored_offers()[0].offer.source == "second_api"
    legacy_after_write = store.get_scored_offer("public_ats", "legacy-001")
    assert legacy_after_write.offer.description == "Coordinate legacy analytics."
    assert legacy_after_write.offer.url == "https://legacy.example/jobs/legacy-001"

    reopened = RadarStore(path)
    assert reopened.get_scored_offer("public_ats", "legacy-001").facts[0].citation == (
        "legacy analytics"
    )
    with sqlite3.connect(path) as connection:
        fact_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(offer_facts)")
        }
        score_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(offer_scores)")
        }
        raw_payload = connection.execute(
            "SELECT raw_payload_json FROM offer_sources WHERE source = 'second_api'"
        ).fetchone()[0]
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

    assert "source_fingerprint" in fact_columns
    assert "source_fingerprint" in score_columns
    assert json.loads(raw_payload)["description"] == (
        "A second API cites workflow governance."
    )


def test_reopening_normalizes_historical_source_identity_without_losing_provenance(
    tmp_path,
):
    path = tmp_path / "historical-source.db"
    store = RadarStore(path)
    scored = _second_provenance().model_copy(
        update={
            "offer": _second_provenance().offer.model_copy(
                update={"source": "public ats", "external_id": "legacy-source-001"}
            )
        }
    )
    store.save_scored_offer(scored, processed_at=FIXED_NOW)
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        row = connection.execute(
            "SELECT id, raw_payload_json FROM offer_sources"
        ).fetchone()
        payload = json.loads(row[1])
        payload["source"] = "Public ATS"
        connection.execute(
            "UPDATE offer_sources SET source = 'Public ATS', "
            "fingerprint = 'Public ATS:legacy-source-001', raw_payload_json = ? "
            "WHERE id = ?",
            (json.dumps(payload, sort_keys=True), row[0]),
        )

    reopened = RadarStore(path)
    restored = reopened.get_scored_offer("PUBLIC ATS", "legacy-source-001")
    with sqlite3.connect(path) as connection:
        identities = connection.execute(
            "SELECT source, external_id, fingerprint FROM offer_sources"
        ).fetchall()

    assert restored.offer.source == "public ats"
    assert identities == [
        ("public ats", "legacy-source-001", '["public ats","legacy-source-001"]')
    ]


def test_reopening_merges_historical_source_health_keys_idempotently(tmp_path):
    path = tmp_path / "historical-health.db"
    RadarStore(path)
    with sqlite3.connect(path) as connection:
        connection.executemany(
            "INSERT INTO source_health "
            "(source, status, last_success_at, quota_remaining, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                (
                    "local_demo",
                    "failed",
                    "2026-08-19T08:00:00+00:00",
                    3,
                    "2026-08-20T08:00:00+00:00",
                ),
                (
                    "LOCAL_DEMO",
                    "ok",
                    "2026-08-25T08:00:00+00:00",
                    8,
                    "2026-08-25T08:00:00+00:00",
                ),
            ],
        )

    RadarStore(path)
    RadarStore(path)
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT source, status, last_success_at, quota_remaining, updated_at "
            "FROM source_health"
        ).fetchall()

    assert rows == [
        (
            "local_demo",
            "ok",
            "2026-08-25T08:00:00+00:00",
            8,
            "2026-08-25T08:00:00+00:00",
        )
    ]


def test_failed_task3_migration_rolls_back_schema_and_version(tmp_path):
    path = tmp_path / "unmigratable.db"
    _create_task3_database(path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            INSERT INTO offers (
                id, canonical_key, title, company, location, contract, remote,
                description, published_at
            ) VALUES (2, 'orphan', 'Orphan role', 'Orphan Co', 'Paris',
                      'permanent', 'onsite', 'No source row.', ?)
            """,
            (FIXED_NOW.isoformat(),),
        )
        connection.execute(
            """
            INSERT INTO offer_facts (
                offer_id, name, value, citation, confidence, extracted_at, facts_version
            ) VALUES (2, 'skill', 'orphan', 'orphan', 50, ?, 'legacy-v1')
            """,
            (FIXED_NOW.isoformat(),),
        )

    with pytest.raises(sqlite3.IntegrityError):
        RadarStore(path)

    with sqlite3.connect(path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(offer_facts)")
        }
        legacy_tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE name LIKE '%_legacy'"
        ).fetchall()
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM offer_facts").fetchone()[0] == 2

    assert "source_fingerprint" not in columns
    assert legacy_tables == []
