from __future__ import annotations

import json
import os
import sqlite3
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from job_radar.db.store import RadarStore
from job_radar.models import OfferFact, RawOffer, ScoreBreakdown, ScoredOffer

FIXED_NOW = datetime(2026, 8, 26, 9, 30, tzinfo=UTC)


def _scored_offer(
    *,
    published_at: datetime = FIXED_NOW,
    source: str = "public_ats",
    external_id: str = "offer-001",
    url: str = "https://jobs.example.com/offers/offer-001",
) -> ScoredOffer:
    offer = RawOffer(
        external_id=external_id,
        source=source,
        url=url,
        title="Product Operations Analyst",
        company="Northstar Works",
        location="Paris",
        contract="permanent",
        remote="hybrid",
        description="Coordinate product operations and analytics.",
        published_at=published_at,
    )
    return ScoredOffer(
        offer=offer,
        facts=[
            OfferFact(
                name="skill",
                value="analytics",
                citation="Coordinate product operations and analytics.",
                confidence=90,
            )
        ],
        axes=[ScoreBreakdown(name="role", points=70, explanation="Role matches.")],
        relevance=70,
        confidence=90,
        freshness_days=0,
        decision="review",
        score_version="demo-v1",
    )


def test_schema_creates_the_public_tables(tmp_path):
    store = RadarStore(tmp_path / "radar.db")

    assert store.table_names() == {
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


def test_store_creates_private_permissions(tmp_path):
    data_dir = tmp_path / "data"
    database = data_dir / "radar.db"
    previous_umask = os.umask(0)
    try:
        RadarStore(database)
    finally:
        os.umask(previous_umask)

    assert stat.S_IMODE(data_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(database.stat().st_mode) == 0o600


def test_store_allows_relative_database_in_existing_permissive_cwd(
    tmp_path, monkeypatch
):
    tmp_path.chmod(0o755)
    monkeypatch.chdir(tmp_path)

    store = RadarStore(Path("demo.db"))

    assert store.table_names()
    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o755
    assert stat.S_IMODE((tmp_path / "demo.db").stat().st_mode) == 0o600


def test_relative_database_still_refuses_permissive_existing_file(
    tmp_path, monkeypatch
):
    tmp_path.chmod(0o755)
    database = tmp_path / "demo.db"
    database.touch(mode=0o644)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="file permissions"):
        RadarStore(Path("demo.db"))

    assert stat.S_IMODE(database.stat().st_mode) == 0o644


def test_relative_database_still_refuses_symlink(tmp_path, monkeypatch):
    tmp_path.chmod(0o755)
    target = tmp_path / "outside.db"
    target.touch(mode=0o600)
    (tmp_path / "demo.db").symlink_to(target)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="symbolic link"):
        RadarStore(Path("demo.db"))

    assert target.stat().st_size == 0


def test_store_refuses_permissive_existing_directory_without_chmod(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(mode=0o755)
    database = data_dir / "radar.db"

    with pytest.raises(ValueError, match="permissions"):
        RadarStore(database)

    assert stat.S_IMODE(data_dir.stat().st_mode) == 0o755
    assert not database.exists()


def test_store_refuses_symlinked_data_directory(tmp_path):
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    data_dir = tmp_path / "data"
    data_dir.symlink_to(target, target_is_directory=True)

    with pytest.raises(ValueError, match="symbolic link"):
        RadarStore(data_dir / "radar.db")

    assert list(target.iterdir()) == []


def test_save_scored_offer_persists_provenance_facts_and_score_in_one_transaction(
    tmp_path,
):
    store = RadarStore(tmp_path / "radar.db")

    store.save_scored_offer(_scored_offer(), processed_at=FIXED_NOW)

    saved = store.get_scored_offer("public_ats", "offer-001")
    assert saved.offer.title == "Product Operations Analyst"
    assert saved.facts[0].citation == "Coordinate product operations and analytics."
    assert saved.axes[0].points == 70
    assert saved.relevance == 70
    assert store.offer_fingerprints() == ['["public_ats","offer-001"]']


def test_processing_timestamps_use_the_injected_clock_not_publication_time(tmp_path):
    store = RadarStore(tmp_path / "radar.db")
    published_at = FIXED_NOW - timedelta(days=45)

    store.save_scored_offer(
        _scored_offer(published_at=published_at), processed_at=FIXED_NOW
    )

    with sqlite3.connect(store.path) as connection:
        row = connection.execute(
            """
            SELECT o.published_at, os.first_seen_at, os.last_seen_at,
                   f.extracted_at, s.scored_at
            FROM offers AS o
            JOIN offer_sources AS os ON os.offer_id = o.id
            JOIN offer_facts AS f ON f.offer_id = o.id
            JOIN offer_scores AS s ON s.offer_id = o.id
            """
        ).fetchone()

    assert row == (
        published_at.isoformat(),
        FIXED_NOW.isoformat(),
        FIXED_NOW.isoformat(),
        FIXED_NOW.isoformat(),
        FIXED_NOW.isoformat(),
    )


def test_failed_save_rolls_back_rows_written_before_the_late_sql_failure(tmp_path):
    store = RadarStore(tmp_path / "radar.db")

    with pytest.raises(sqlite3.IntegrityError):
        store.save_scored_offer(
            _scored_offer(), processed_at=FIXED_NOW, profile_id=None
        )

    with sqlite3.connect(store.path) as connection:
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("offers", "offer_sources", "offer_facts", "offer_scores")
        }

    assert counts == {
        "offers": 0,
        "offer_sources": 0,
        "offer_facts": 0,
        "offer_scores": 0,
    }


def test_save_scored_batch_is_atomic_when_a_late_offer_is_invalid(tmp_path):
    store = RadarStore(tmp_path / "radar.db")
    invalid = _scored_offer(
        external_id="offer-002",
        url="https://jobs.example.com/offers/offer-002",
        published_at=FIXED_NOW.replace(tzinfo=None),
    )

    with pytest.raises(ValueError, match="timezone"):
        store.save_scored_batch(
            [_scored_offer(), invalid],
            canonical_keys=["canonical-one", "canonical-two"],
            processed_at=FIXED_NOW,
        )

    with sqlite3.connect(store.path) as connection:
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("offers", "offer_sources", "offer_facts", "offer_scores")
        }
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

    assert counts == {
        "offers": 0,
        "offer_sources": 0,
        "offer_facts": 0,
        "offer_scores": 0,
    }


def test_stable_identity_resolution_rolls_back_with_a_late_invalid_offer(tmp_path):
    store = RadarStore(tmp_path / "stable-rollback.db")
    initial = _scored_offer()
    store.save_scored_offer(
        initial, canonical_key="original-canonical", processed_at=FIXED_NOW
    )
    with sqlite3.connect(store.path) as connection:
        offer_id = connection.execute("SELECT id FROM offers").fetchone()[0]
        connection.execute(
            "INSERT INTO user_feedback (offer_id, value, note, created_at) "
            "VALUES (?, 'relevant', 'survives rollback', ?)",
            (offer_id, FIXED_NOW.isoformat()),
        )
    updated = initial.model_copy(
        update={
            "offer": initial.offer.model_copy(
                update={"title": "Senior Product Operations Analyst"}
            )
        }
    )
    invalid = _scored_offer(
        source="second_ats",
        external_id="invalid-late",
        url="https://second.example/invalid-late",
        published_at=FIXED_NOW.replace(tzinfo=None),
    )

    with pytest.raises(ValueError, match="timezone"):
        store.save_scored_batch(
            [updated, invalid],
            canonical_keys=["conflicting-new-key", "invalid-key"],
            processed_at=FIXED_NOW,
        )

    saved = store.get_scored_offer("public_ats", "offer-001")
    with sqlite3.connect(store.path) as connection:
        state = connection.execute(
            "SELECT o.id, o.canonical_key, f.note FROM offers AS o "
            "JOIN user_feedback AS f ON f.offer_id = o.id"
        ).fetchall()
    assert saved.offer.title == initial.offer.title
    assert state == [(offer_id, "original-canonical", "survives rollback")]


def test_batch_keeps_every_provenance_on_one_canonical_offer(tmp_path):
    store = RadarStore(tmp_path / "radar.db")
    first = _scored_offer()
    second = _scored_offer(
        source="second_ats",
        external_id="second-001",
        url="https://second.example/jobs/second-001",
    )
    second = second.model_copy(
        update={
            "offer": second.offer.model_copy(
                update={"description": "A second source cites workflow governance."}
            ),
            "facts": [
                OfferFact(
                    name="skill",
                    value="workflow governance",
                    citation="workflow governance",
                    confidence=85,
                )
            ],
        }
    )

    store.save_scored_batch(
        [first, second],
        canonical_keys=["northstar|product-operations|paris"] * 2,
        processed_at=FIXED_NOW,
    )

    assert len(store.list_scored_offers()) == 1
    assert store.offer_fingerprints() == [
        '["public_ats","offer-001"]',
        '["second_ats","second-001"]',
    ]
    listed = store.list_scored_offers()[0]
    assert listed.offer.source == "public_ats"
    assert {fact.citation for fact in listed.facts} == {
        "Coordinate product operations and analytics."
    }
    assert {
        fact.citation
        for fact in store.get_scored_offer("second_ats", "second-001").facts
    } == {"workflow governance"}
    assert store.list_provenance("public_ats", "offer-001") == [
        {
            "source": "public_ats",
            "external_id": "offer-001",
            "url": "https://jobs.example.com/offers/offer-001",
        },
        {
            "source": "second_ats",
            "external_id": "second-001",
            "url": "https://second.example/jobs/second-001",
        },
    ]
    assert (
        store.get_scored_offer("second_ats", "second-001").offer.source == "second_ats"
    )


def test_source_fingerprint_structurally_encodes_separator_bearing_identity():
    first = _scored_offer(source="alpha:beta", external_id="gamma").offer
    second = _scored_offer(source="alpha", external_id="beta:gamma").offer

    first_fingerprint = RadarStore._fingerprint(first)
    second_fingerprint = RadarStore._fingerprint(second)

    assert first_fingerprint != second_fingerprint
    assert json.loads(first_fingerprint) == ["alpha:beta", "gamma"]
    assert json.loads(second_fingerprint) == ["alpha", "beta:gamma"]


@pytest.mark.parametrize("value", ["50", 50.0, True])
@pytest.mark.parametrize(
    "factory",
    [
        lambda value: OfferFact(
            name="skill", value="analytics", citation="excerpt", confidence=value
        ),
        lambda value: ScoreBreakdown(name="role", points=value, explanation="match"),
        lambda value: ScoredOffer.model_validate(
            _scored_offer().model_dump()
            | {
                "axes": [{"name": "role", "points": value, "explanation": "match"}],
                "relevance": value,
            }
        ),
        lambda value: ScoredOffer.model_validate(
            _scored_offer().model_dump() | {"confidence": value}
        ),
        lambda value: ScoredOffer.model_validate(
            _scored_offer().model_dump() | {"freshness_days": value}
        ),
    ],
)
def test_numeric_fields_reject_coercion(value, factory):
    with pytest.raises(ValidationError):
        factory(value)


def test_models_reject_extra_fields():
    with pytest.raises(ValidationError):
        OfferFact(
            name="skill",
            value="analytics",
            citation="excerpt",
            confidence=90,
            unknown="value",
        )
