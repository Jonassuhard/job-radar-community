from __future__ import annotations

import sqlite3

import pytest

from job_radar.config import AppConfig
from job_radar.db.store import RadarStore
from job_radar.pipeline.refresh import SourcePolicyError, import_offers, run_refresh

from .conftest import FIXED_NOW


@pytest.mark.parametrize("source", ["linkedin", "indeed", "wttj"])
def test_manual_sources_cannot_refresh(source, config, tmp_path):
    with pytest.raises(SourcePolicyError, match="manual_only"):
        run_refresh(
            config=config,
            source_names=[source],
            store=RadarStore(tmp_path / "radar.db"),
            connectors={},
            now=FIXED_NOW,
        )


@pytest.mark.parametrize(
    "source",
    [
        "LinkedIn Jobs",
        "linkedin_jobs",
        "Indeed Jobs",
        "welcome_to_the_jungle",
        "WelcomeToTheJungle",
    ],
)
def test_protected_source_aliases_cannot_refresh(source, config, tmp_path):
    with pytest.raises(SourcePolicyError, match="manual_only"):
        run_refresh(
            config=config,
            source_names=[source],
            store=RadarStore(tmp_path / "radar.db"),
        )


def test_refresh_scores_deduplicates_and_persists_connector_offers(
    config, matching_offer, tmp_path
):
    duplicate = matching_offer.model_copy(
        update={
            "external_id": "offer-duplicate",
            "url": "https://careers.example/offers/duplicate",
        }
    )

    class StaticConnector:
        def fetch(self, config, client):
            del config, client
            return [matching_offer, duplicate]

    store = RadarStore(tmp_path / "radar.db")
    result = run_refresh(
        config=config,
        source_names=["public_ats"],
        store=store,
        connectors={"public_ats": StaticConnector()},
        now=FIXED_NOW,
    )

    assert result.offers_seen == 2
    assert result.offers_saved == 1
    assert len(store.list_scored_offers()) == 1


def test_disabled_or_unconfigured_network_stub_is_a_noop(config, tmp_path):
    store = RadarStore(tmp_path / "radar.db")

    result = run_refresh(
        config=config,
        source_names=["local_demo"],
        store=store,
        connectors={},
        now=FIXED_NOW,
    )

    assert result.offers_seen == 0
    assert result.offers_saved == 0
    assert result.skipped_sources == ("local_demo",)


def test_manual_import_remains_available_for_manual_only_sources(
    config, matching_offer, tmp_path
):
    store = RadarStore(tmp_path / "radar.db")
    manual_offer = matching_offer.model_copy(update={"source": "linkedin"})

    result = import_offers([manual_offer], config=config, store=store, now=FIXED_NOW)

    assert result.offers_seen == 1
    assert result.offers_saved == 1
    assert store.get_scored_offer("linkedin", "offer-001").offer == manual_offer


def test_connector_cannot_inject_a_manual_only_offer(config, matching_offer, tmp_path):
    class SpoofedConnector:
        def fetch(self, config, client):
            del config, client
            return [
                matching_offer,
                matching_offer.model_copy(
                    update={"external_id": "spoofed", "source": "linkedin"}
                ),
            ]

    store = RadarStore(tmp_path / "radar.db")

    with pytest.raises(SourcePolicyError, match="manual_only"):
        run_refresh(
            config=config,
            source_names=["public_ats"],
            store=store,
            connectors={"public_ats": SpoofedConnector()},
            now=FIXED_NOW,
        )

    assert store.list_scored_offers() == []


@pytest.mark.parametrize(
    "url",
    [
        "https://jobs.linkedin.com/view/123",
        "https://uk.indeed.com/viewjob?jk=123",
        "https://www.welcometothejungle.com/jobs/123",
        "https://jobs.wttj.co/positions/123",
    ],
)
def test_connector_cannot_inject_a_protected_hostname(
    config, matching_offer, tmp_path, url
):
    class ProtectedHostnameConnector:
        def fetch(self, config, client):
            del config, client
            return [matching_offer.model_copy(update={"url": url})]

    store = RadarStore(tmp_path / "radar.db")

    with pytest.raises(SourcePolicyError, match="manual_only"):
        run_refresh(
            config=config,
            source_names=["public_ats"],
            store=store,
            connectors={"public_ats": ProtectedHostnameConnector()},
            now=FIXED_NOW,
        )

    assert store.list_scored_offers() == []


def test_connector_hostname_matching_is_not_a_substring_check(
    config, matching_offer, tmp_path
):
    safe_offer = matching_offer.model_copy(
        update={"url": "https://notlinkedin.example/jobs/123"}
    )

    class SafeConnector:
        def fetch(self, config, client):
            del config, client
            return [safe_offer]

    store = RadarStore(tmp_path / "radar.db")
    result = run_refresh(
        config=config,
        source_names=["public_ats"],
        store=store,
        connectors={"public_ats": SafeConnector()},
        now=FIXED_NOW,
    )

    assert result.offers_saved == 1


def test_connector_offer_source_must_match_requested_automated_source(
    config, matching_offer, tmp_path
):
    payload = config.model_dump()
    payload["sources"]["sources"]["second_ats"] = {"mode": "ats"}
    expanded_config = AppConfig.model_validate(payload)

    class MismatchedConnector:
        def fetch(self, config, client):
            del config, client
            return [matching_offer.model_copy(update={"source": "second_ats"})]

    store = RadarStore(tmp_path / "radar.db")

    with pytest.raises(SourcePolicyError, match="does not match"):
        run_refresh(
            config=expanded_config,
            source_names=["public_ats"],
            store=store,
            connectors={"public_ats": MismatchedConnector()},
            now=FIXED_NOW,
        )

    assert store.list_scored_offers() == []


def test_custom_manual_only_source_cannot_refresh(config):
    payload = config.model_dump()
    payload["sources"]["sources"]["manual_board"] = {"mode": "manual_only"}
    expanded_config = AppConfig.model_validate(payload)

    with pytest.raises(SourcePolicyError, match="manual_only"):
        run_refresh(config=expanded_config, source_names=["manual_board"])


def test_explicit_manual_import_allows_protected_alias_and_hostname(
    config, matching_offer, tmp_path
):
    store = RadarStore(tmp_path / "radar.db")
    offer = matching_offer.model_copy(
        update={
            "source": "welcome_to_the_jungle",
            "url": "https://www.welcometothejungle.com/jobs/manual-123",
        }
    )

    result = import_offers([offer], config=config, store=store, now=FIXED_NOW)

    assert result.offers_saved == 1
    assert store.get_scored_offer("welcome_to_the_jungle", "offer-001").offer.url == offer.url


def test_manual_import_preview_scores_without_writing(config, matching_offer, tmp_path):
    store = RadarStore(tmp_path / "radar.db")
    offer = matching_offer.model_copy(
        update={
            "source": "linkedin",
            "url": "https://www.linkedin.com/jobs/view/preview-001",
        }
    )

    result = import_offers(
        [offer], config=config, store=store, now=FIXED_NOW, preview=True
    )

    assert result.offers_seen == 1
    assert result.offers_saved == 1
    assert store.list_scored_offers() == []


def _stable_manual_offer(matching_offer, *, source: str, external_id: str, title: str):
    return matching_offer.model_copy(
        update={
            "source": source,
            "external_id": external_id,
            "url": f"https://manual.example/jobs/{external_id}",
            "title": title,
            "description": f"{title}. Product analytics and workflow design.",
        }
    )


def _feedback_state(store: RadarStore) -> tuple[int, str, int]:
    with sqlite3.connect(store.path) as connection:
        return connection.execute(
            "SELECT o.id, o.canonical_key, COUNT(f.id) "
            "FROM offers AS o LEFT JOIN user_feedback AS f ON f.offer_id = o.id "
            "GROUP BY o.id, o.canonical_key ORDER BY o.id"
        ).fetchone()


def test_stable_provenance_update_preserves_offer_id_and_feedback(
    config, matching_offer, tmp_path
):
    store = RadarStore(tmp_path / "stable-update.db")
    initial = _stable_manual_offer(
        matching_offer,
        source="linkedin",
        external_id="stable-1",
        title="Product Analyst",
    )
    updated = _stable_manual_offer(
        matching_offer,
        source="linkedin",
        external_id="stable-1",
        title="Senior Product Analyst",
    )
    import_offers([initial], config=config, store=store, now=FIXED_NOW)
    offer_id, original_key, _feedback_count = _feedback_state(store)
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "INSERT INTO user_feedback (offer_id, value, note, created_at) "
            "VALUES (?, 'relevant', 'keep me', ?)",
            (offer_id, FIXED_NOW.isoformat()),
        )

    first = import_offers([updated], config=config, store=store, now=FIXED_NOW)
    second = import_offers([updated], config=config, store=store, now=FIXED_NOW)
    saved = store.get_scored_offer("linkedin", "stable-1")
    with sqlite3.connect(store.path) as connection:
        state = connection.execute(
            "SELECT o.id, o.canonical_key, COUNT(f.id), COUNT(os.id) "
            "FROM offers AS o LEFT JOIN user_feedback AS f ON f.offer_id = o.id "
            "JOIN offer_sources AS os ON os.offer_id = o.id "
            "GROUP BY o.id, o.canonical_key"
        ).fetchall()

    assert first.offers_saved == second.offers_saved == 1
    assert state == [(offer_id, original_key, 1, 1)]
    assert saved.offer.title == "Senior Product Analyst"


def test_stable_update_keeps_multi_provenance_group_together(
    config, matching_offer, tmp_path
):
    store = RadarStore(tmp_path / "multi-provenance-update.db")
    initial = _stable_manual_offer(
        matching_offer,
        source="linkedin",
        external_id="stable-1",
        title="Product Analyst",
    )
    sibling = _stable_manual_offer(
        matching_offer,
        source="indeed",
        external_id="sibling-1",
        title="Product Analyst",
    )
    updated = _stable_manual_offer(
        matching_offer,
        source="linkedin",
        external_id="stable-1",
        title="Senior Product Analyst",
    )
    import_offers([initial, sibling], config=config, store=store, now=FIXED_NOW)

    import_offers([updated], config=config, store=store, now=FIXED_NOW)

    with sqlite3.connect(store.path) as connection:
        offer_count = connection.execute("SELECT COUNT(*) FROM offers").fetchone()[0]
        groups = connection.execute(
            "SELECT offer_id, COUNT(*) FROM offer_sources GROUP BY offer_id"
        ).fetchall()
    assert offer_count == 1
    assert groups == [(groups[0][0], 2)]
    assert {item["source"] for item in store.list_provenance("linkedin", "stable-1")} == {
        "indeed",
        "linkedin",
    }


def test_stable_update_does_not_merge_with_an_existing_canonical_collision(
    config, matching_offer, tmp_path
):
    store = RadarStore(tmp_path / "canonical-collision.db")
    initial = _stable_manual_offer(
        matching_offer,
        source="linkedin",
        external_id="stable-1",
        title="Product Analyst",
    )
    existing_collision = _stable_manual_offer(
        matching_offer,
        source="indeed",
        external_id="distinct-1",
        title="Senior Product Analyst",
    )
    import_offers([initial], config=config, store=store, now=FIXED_NOW)
    first_id, first_key, _feedback_count = _feedback_state(store)
    import_offers([existing_collision], config=config, store=store, now=FIXED_NOW)
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "INSERT INTO user_feedback (offer_id, value, note, created_at) "
            "VALUES (?, 'relevant', 'keep collision separate', ?)",
            (first_id, FIXED_NOW.isoformat()),
        )
    updated = _stable_manual_offer(
        matching_offer,
        source="linkedin",
        external_id="stable-1",
        title="Senior Product Analyst",
    )

    import_offers([updated], config=config, store=store, now=FIXED_NOW)

    with sqlite3.connect(store.path) as connection:
        offers = connection.execute(
            "SELECT id, canonical_key FROM offers ORDER BY id"
        ).fetchall()
        feedback = connection.execute(
            "SELECT offer_id, note FROM user_feedback"
        ).fetchall()
        provenance = connection.execute(
            "SELECT source, external_id, offer_id FROM offer_sources ORDER BY source"
        ).fetchall()
    assert len(offers) == 2
    assert (first_id, first_key) in offers
    assert feedback == [(first_id, "keep collision separate")]
    assert {row[2] for row in provenance} == {row[0] for row in offers}


def test_deduplication_survives_separate_refreshes_and_keeps_both_urls(
    config, matching_offer, tmp_path
):
    class StaticConnector:
        def __init__(self, offer):
            self.offer = offer

        def fetch(self, config, client):
            del config, client
            return [self.offer]

    store = RadarStore(tmp_path / "radar.db")
    second = matching_offer.model_copy(
        update={
            "external_id": "offer-002",
            "url": "https://careers.example/offers/offer-002",
        }
    )

    for offer in (matching_offer, second):
        run_refresh(
            config=config,
            source_names=["public_ats"],
            store=store,
            connectors={"public_ats": StaticConnector(offer)},
            now=FIXED_NOW,
        )

    assert len(store.list_scored_offers()) == 1
    assert store.list_provenance("public_ats", "offer-001") == [
        {
            "source": "public_ats",
            "external_id": "offer-001",
            "url": "https://careers.example/offers/offer-001",
        },
        {
            "source": "public_ats",
            "external_id": "offer-002",
            "url": "https://careers.example/offers/offer-002",
        },
    ]


def test_deduplication_keeps_provenance_from_distinct_automated_sources(
    config, matching_offer, tmp_path
):
    payload = config.model_dump()
    payload["sources"]["sources"]["second_ats"] = {"mode": "ats"}
    expanded_config = AppConfig.model_validate(payload)
    second = matching_offer.model_copy(
        update={
            "source": "second_ats",
            "external_id": "second-001",
            "url": "https://second.example/jobs/second-001",
        }
    )

    class StaticConnector:
        def __init__(self, offer):
            self.offer = offer

        def fetch(self, config, client):
            del config, client
            return [self.offer]

    store = RadarStore(tmp_path / "radar.db")
    for source, offer in (("public_ats", matching_offer), ("second_ats", second)):
        run_refresh(
            config=expanded_config,
            source_names=[source],
            store=store,
            connectors={source: StaticConnector(offer)},
            now=FIXED_NOW,
        )

    assert len(store.list_scored_offers()) == 1
    assert {
        item["source"] for item in store.list_provenance("public_ats", "offer-001")
    } == {"public_ats", "second_ats"}


@pytest.mark.parametrize("operation", ["refresh", "import"])
def test_pipeline_batches_roll_back_when_a_late_offer_fails(
    operation, config, matching_offer, tmp_path
):
    invalid = matching_offer.model_copy(
        update={
            "external_id": "offer-invalid",
            "url": "https://careers.example/offers/offer-invalid",
            "published_at": matching_offer.published_at.replace(tzinfo=None),
        }
    )
    store = RadarStore(tmp_path / "radar.db")

    if operation == "refresh":

        class StaticConnector:
            def fetch(self, config, client):
                del config, client
                return [matching_offer, invalid]

        def invoke():
            return run_refresh(
                config=config,
                source_names=["public_ats"],
                store=store,
                connectors={"public_ats": StaticConnector()},
                now=FIXED_NOW,
            )

    else:

        def invoke():
            return import_offers(
                [matching_offer, invalid], config=config, store=store, now=FIXED_NOW
            )

    with pytest.raises(ValueError, match="timezone"):
        invoke()

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


def test_canonical_serialization_is_identical_in_both_refresh_orders(
    config, matching_offer, tmp_path
):
    payload = config.model_dump()
    payload["sources"]["sources"]["second_api"] = {"mode": "api"}
    expanded_config = AppConfig.model_validate(payload)
    api_offer = matching_offer.model_copy(
        update={
            "source": "second_api",
            "external_id": "api-001",
            "url": "https://api.example/jobs/api-001",
            "description": matching_offer.description.replace(
                "process design", "workflow design"
            ),
        }
    )

    class StaticConnector:
        def __init__(self, offer):
            self.offer = offer

        def fetch(self, config, client):
            del config, client
            return [self.offer]

    def materialize(path, ordered_offers):
        store = RadarStore(path)
        for offer in ordered_offers:
            run_refresh(
                config=expanded_config,
                source_names=[offer.source],
                store=store,
                connectors={offer.source: StaticConnector(offer)},
                now=FIXED_NOW,
            )
        canonical = store.list_scored_offers()[0]
        return {
            "canonical": canonical.model_dump(mode="json"),
            "provenance": store.list_provenance("public_ats", "offer-001"),
            "ats": store.get_scored_offer("public_ats", "offer-001").model_dump(
                mode="json"
            ),
            "api": store.get_scored_offer("second_api", "api-001").model_dump(
                mode="json"
            ),
        }

    first = materialize(tmp_path / "ats-first.db", [matching_offer, api_offer])
    second = materialize(tmp_path / "api-first.db", [api_offer, matching_offer])

    assert first == second
    assert first["canonical"]["offer"]["source"] == "second_api"
    assert first["canonical"]["confidence"] == first["api"]["confidence"]
    assert {fact["citation"] for fact in first["canonical"]["facts"]} == {
        fact["citation"] for fact in first["api"]["facts"]
    }
    assert first["ats"]["confidence"] != first["api"]["confidence"]
    assert "process design" in {fact["citation"] for fact in first["ats"]["facts"]}
    assert "workflow design" in {fact["citation"] for fact in first["api"]["facts"]}
