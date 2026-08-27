from __future__ import annotations

import json
import sqlite3
import stat
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from job_radar.api import routes
from job_radar.api.app import ApiSettings, create_app
from job_radar.config.loader import initialize_config, load_config
from job_radar.db.store import RadarStore
from job_radar.demo import seed_demo
from job_radar.models import OfferFact, RawOffer, ScoreBreakdown, ScoredOffer

FIXED_NOW = datetime(2026, 8, 26, 9, 30, tzinfo=UTC)
FORBIDDEN = {"application_id", "candidature", "worker", "cv", "email"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(routes, "_utc_now", lambda: FIXED_NOW)
    config_dir = tmp_path / "config"
    initialize_config(config_dir)
    store = RadarStore(tmp_path / "job-radar.db")
    seed_demo(store, FIXED_NOW)
    application = create_app(
        ApiSettings(
            data_dir=tmp_path,
            config_dir=config_dir,
            allow_testclient=True,
        )
    )
    with TestClient(application) as test_client:
        yield test_client


def _auth(client: TestClient) -> dict[str, str]:
    return {"X-Job-Radar-Token": client.app.state.session_token}


def _manual_offer_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "external_id": "manual-api-001",
        "source": "linkedin",
        "url": "https://www.linkedin.com/jobs/view/manual-api-001",
        "title": "Product Operations Analyst",
        "company": "Example Workshop",
        "location": "Paris",
        "contract": "permanent",
        "remote": "hybrid",
        "description": "Product operations and analytics.",
        "published_at": "2026-08-27T08:00:00Z",
    }
    payload.update(overrides)
    return payload


def _keys(value) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for child in value.values() for key in _keys(child)}
    if isinstance(value, list):
        return {key for child in value for key in _keys(child)}
    return set()


def _offer_id(client: TestClient, external_id: str) -> int:
    items = client.get("/api/offers", params={"q": external_id, "limit": 100}).json()[
        "items"
    ]
    return next(
        item["id"]
        for item in items
        if any(source["external_id"] == external_id for source in item["provenance"])
    )


def _scored_collision(source: str, company: str) -> ScoredOffer:
    offer = RawOffer(
        external_id="shared-123",
        source=source,
        url=f"https://{source}.example/shared-123",
        title="Distinct role",
        company=company,
        location="Paris",
        contract="permanent",
        remote="hybrid",
        description=f"A distinct role at {company} with analytics.",
        published_at=FIXED_NOW,
    )
    return ScoredOffer(
        offer=offer,
        facts=[
            OfferFact(
                name="skill", value="analytics", citation="analytics", confidence=90
            )
        ],
        axes=[ScoreBreakdown(name="role", points=70, explanation="Match")],
        relevance=70,
        confidence=90,
        freshness_days=0,
        decision="review",
        score_version="test-v1",
    )


def _scored_provenance(
    *,
    source: str,
    external_id: str,
    description: str,
    published_at: datetime,
    confidence: int,
) -> ScoredOffer:
    offer = RawOffer(
        external_id=external_id,
        source=source,
        url=f"https://{source}.example/jobs/{external_id}",
        title="Provenance Integration Role",
        company="Canonical Workshop",
        location="Paris",
        contract="permanent",
        remote="hybrid",
        description=description,
        published_at=published_at,
    )
    return ScoredOffer(
        offer=offer,
        facts=[
            OfferFact(
                name="skill",
                value="analytics",
                citation="integration-marker",
                confidence=confidence,
            )
        ],
        axes=[ScoreBreakdown(name="role", points=70, explanation="Match")],
        relevance=70,
        confidence=confidence,
        freshness_days=max(0, (FIXED_NOW.date() - published_at.date()).days),
        decision="review",
        score_version="test-v1",
    )


def test_health_and_offer_page_are_runnable_from_local_database(client):
    assert client.get("/health").json() == {"status": "ok", "schema_version": 2}
    page = client.get(
        "/api/offers", params={"decision": "prioritize", "limit": 4, "offset": 0}
    ).json()
    assert page["total"] == 10
    assert page["limit"] == 4
    assert page["offset"] == 0
    assert len(page["items"]) == 4
    assert isinstance(page["items"][0]["id"], int)
    assert all(offer["decision"] == "prioritize" for offer in page["items"])


def test_offer_detail_never_exposes_application_data(client):
    offer_id = _offer_id(client, "demo-001")
    response = client.get(f"/api/offers/{offer_id}")
    assert response.status_code == 200
    assert FORBIDDEN.isdisjoint(_keys(response.json()))
    assert response.json()["facts"][0]["citation"]
    assert response.json()["provenance"][0]["external_id"] == "demo-001"


def test_offer_compare_uses_canonical_integer_ids(client):
    offer_id = _offer_id(client, "demo-001")
    payload = client.get(
        "/api/offers/compare", params=[("ids", offer_id), ("ids", 999999)]
    ).json()
    assert [offer["id"] for offer in payload["offers"]] == [offer_id]
    assert payload["missing"] == [999999]


def test_offer_compare_rejects_more_than_three_ids(client):
    offer_ids = [
        offer["id"]
        for offer in client.get("/api/offers", params={"limit": 4}).json()["items"]
    ]

    get_response = client.get(
        "/api/offers/compare", params=[("ids", offer_id) for offer_id in offer_ids]
    )
    post_response = client.post("/api/offers/compare", json={"ids": offer_ids})

    assert get_response.status_code == 422
    assert post_response.status_code == 422


def test_same_external_id_from_two_sources_remains_unambiguous(client):
    store = client.app.state.store
    store.save_scored_offer(
        _scored_collision("adzuna", "Alpha Works"),
        canonical_key="alpha|distinct|paris",
        processed_at=FIXED_NOW,
    )
    store.save_scored_offer(
        _scored_collision("jooble", "Beta Works"),
        canonical_key="beta|distinct|paris",
        processed_at=FIXED_NOW,
    )
    page = client.get("/api/offers", params={"q": "Distinct role", "limit": 100}).json()
    collisions = [
        offer
        for offer in page["items"]
        if offer["company"] in {"Alpha Works", "Beta Works"}
    ]
    assert len({offer["id"] for offer in collisions}) == 2
    beta = next(offer for offer in collisions if offer["company"] == "Beta Works")
    feedback = client.post(
        f"/api/offers/{beta['id']}/feedback",
        json={"value": "relevant"},
        headers=_auth(client),
    )
    assert feedback.json()["offer_id"] == beta["id"]
    with sqlite3.connect(store.path) as connection:
        company = connection.execute(
            "SELECT o.company FROM user_feedback f JOIN offers o ON o.id = f.offer_id"
        ).fetchone()[0]
    assert company == "Beta Works"


def test_offer_page_combines_filters_and_has_stable_allowlisted_sort(client):
    response = client.get(
        "/api/offers",
        params={
            "decision": "review",
            "source": "france_travail",
            "q": "support",
            "min_score": 68,
            "min_confidence": 80,
            "contract": "fixed_term",
            "location": "Lille",
            "remote": "onsite",
            "max_freshness": 20,
            "sort": "relevance_desc",
            "limit": 5,
            "offset": 0,
        },
    )
    assert response.status_code == 200
    page = response.json()
    assert page["total"] == 1
    assert page["items"][0]["relevance"] == 68
    assert page["items"][0]["provenance"][0]["external_id"] == "demo-021"
    assert client.get("/api/offers", params={"limit": 101}).status_code == 422
    assert client.get("/api/offers", params={"sort": "drop_table"}).status_code == 422


def test_offer_page_offsets_without_duplicates(client):
    first = client.get(
        "/api/offers", params={"limit": 5, "offset": 0, "sort": "relevance_desc"}
    ).json()
    second = client.get(
        "/api/offers", params={"limit": 5, "offset": 5, "sort": "relevance_desc"}
    ).json()
    assert first["total"] == second["total"] == 42
    assert len(first["items"]) == len(second["items"]) == 5
    assert {item["id"] for item in first["items"]}.isdisjoint(
        item["id"] for item in second["items"]
    )
    assert first["items"][-1]["relevance"] >= second["items"][0]["relevance"]


def test_canonical_page_uses_the_selected_provenance_payload_for_display_and_sort(
    client,
):
    store = client.app.state.store
    selected_a = _scored_provenance(
        source="selected_a",
        external_id="selected-a",
        description="integration-marker selected-evidence-a",
        published_at=FIXED_NOW - timedelta(days=10),
        confidence=95,
    )
    overwrite_a = _scored_provenance(
        source="overwrite_a",
        external_id="overwrite-a",
        description="integration-marker wrong-overwrite-a",
        published_at=FIXED_NOW,
        confidence=40,
    )
    selected_b = _scored_provenance(
        source="selected_b",
        external_id="selected-b",
        description="integration-marker selected-evidence-b",
        published_at=FIXED_NOW - timedelta(days=5),
        confidence=95,
    )
    overwrite_b = _scored_provenance(
        source="overwrite_b",
        external_id="overwrite-b",
        description="integration-marker wrong-overwrite-b",
        published_at=FIXED_NOW - timedelta(days=20),
        confidence=40,
    )
    for canonical_key, scored in (
        ("canonical-a", selected_a),
        ("canonical-a", overwrite_a),
        ("canonical-b", selected_b),
        ("canonical-b", overwrite_b),
    ):
        store.save_scored_offer(
            scored, canonical_key=canonical_key, processed_at=FIXED_NOW
        )

    page = client.get(
        "/api/offers",
        params={"q": "integration-marker", "sort": "published_desc", "limit": 100},
    ).json()
    recent = client.get(
        "/api/offers",
        params={"q": "integration-marker", "max_freshness": 7, "limit": 100},
    ).json()

    assert [item["source"] for item in page["items"]] == ["selected_b", "selected_a"]
    assert [item["description"] for item in page["items"]] == [
        "integration-marker selected-evidence-b",
        "integration-marker selected-evidence-a",
    ]
    assert [item["freshness_days"] for item in page["items"]] == [5, 10]
    assert [item["source"] for item in recent["items"]] == ["selected_b"]


def test_published_sort_uses_utc_instants_and_keeps_id_ties_deterministic(client):
    store = client.app.state.store
    same_instant_earlier_id = _scored_provenance(
        source="offset_a",
        external_id="offset-a",
        description="timezone-order-marker a",
        published_at=datetime.fromisoformat("2026-08-26T23:30:00-05:00"),
        confidence=90,
    )
    chronologically_older = _scored_provenance(
        source="offset_b",
        external_id="offset-b",
        description="timezone-order-marker b",
        published_at=datetime.fromisoformat("2026-08-27T01:00:00+00:00"),
        confidence=90,
    )
    same_instant_later_id = _scored_provenance(
        source="offset_c",
        external_id="offset-c",
        description="timezone-order-marker c",
        published_at=datetime.fromisoformat("2026-08-27T04:30:00+00:00"),
        confidence=90,
    )
    for canonical_key, scored in (
        ("offset-a", same_instant_earlier_id),
        ("offset-b", chronologically_older),
        ("offset-c", same_instant_later_id),
    ):
        store.save_scored_offer(
            scored, canonical_key=canonical_key, processed_at=FIXED_NOW
        )

    page = client.get(
        "/api/offers",
        params={"q": "timezone-order-marker", "sort": "published_desc"},
    ).json()

    assert [item["source"] for item in page["items"]] == [
        "offset_a",
        "offset_c",
        "offset_b",
    ]


@pytest.mark.parametrize("query", ["%", "_", "\\"])
def test_offer_search_treats_sql_wildcards_as_literal_text(client, query):
    response = client.get("/api/offers", params={"q": query, "limit": 100})

    assert response.status_code == 200
    assert response.json()["total"] == 0
    assert response.json()["items"] == []


def test_offer_search_and_location_filter_use_unicode_casefolding(client):
    offer_id = _offer_id(client, "demo-001")
    with sqlite3.connect(client.app.state.store.path) as connection:
        row = connection.execute(
            "SELECT id, raw_payload_json FROM offer_sources WHERE offer_id = ?",
            (offer_id,),
        ).fetchone()
        payload = json.loads(row[1])
        payload.update({"company": "ÉCOLE Horizon", "location": "À Paris"})
        connection.execute(
            "UPDATE offer_sources SET raw_payload_json = ? WHERE id = ?",
            (json.dumps(payload, sort_keys=True), row[0]),
        )

    searched = client.get("/api/offers", params={"q": "école", "limit": 100}).json()
    filtered = client.get(
        "/api/offers", params={"location": "à paris", "limit": 100}
    ).json()

    assert [item["id"] for item in searched["items"]] == [offer_id]
    assert [item["id"] for item in filtered["items"]] == [offer_id]


def test_offer_freshness_is_recomputed_from_the_current_utc_day(
    client, monkeypatch
):
    monkeypatch.setattr(routes, "_utc_now", lambda: FIXED_NOW)
    day_zero = client.get("/api/offers", params={"q": "demo-001", "limit": 100})

    monkeypatch.setattr(routes, "_utc_now", lambda: FIXED_NOW + timedelta(days=5))
    day_five = client.get("/api/offers", params={"q": "demo-001", "limit": 100})
    stale_filter = client.get(
        "/api/offers",
        params={"q": "demo-001", "max_freshness": 4, "limit": 100},
    )

    assert day_zero.json()["items"][0]["freshness_days"] == 0
    assert day_five.json()["items"][0]["freshness_days"] == 5
    assert stale_filter.json()["total"] == 0


def test_every_mutation_requires_the_ephemeral_session_token(client):
    offer_id = _offer_id(client, "demo-001")
    requests = [
        ("post", f"/api/offers/{offer_id}/feedback", {"value": "relevant"}),
        ("post", "/api/refresh", {"sources": ["local_demo"]}),
        ("post", "/api/rescore", None),
        ("post", "/api/import", [_manual_offer_payload()]),
        ("post", "/api/saved-views", {"name": "Top", "filters": {"score_min": 80}}),
        ("put", "/api/config", client.get("/api/config").json()),
    ]
    for method, path, body in requests:
        response = client.request(method, path, json=body)
        assert response.status_code == 401, path


def test_manual_import_api_previews_then_persists_a_manual_only_offer(client):
    payload = [_manual_offer_payload()]

    preview = client.post(
        "/api/import?preview=true", json=payload, headers=_auth(client)
    )
    before = client.get("/api/offers", params={"limit": 100}).json()["total"]
    imported = client.post("/api/import", json=payload, headers=_auth(client))
    after = client.get("/api/offers", params={"limit": 100}).json()["total"]

    assert preview.status_code == 200
    assert preview.json() == {
        "preview": True,
        "offers_received": 1,
        "offers_seen": 1,
        "offers_saved": 1,
        "errors": [],
    }
    assert imported.status_code == 200
    assert imported.json()["preview"] is False
    assert imported.json()["offers_saved"] == 1
    assert before == 42
    assert after == 43


def test_manual_import_api_reports_indexed_errors_without_partial_writes(client):
    payload = [_manual_offer_payload(), _manual_offer_payload(external_id="bad", unexpected=True)]

    response = client.post("/api/import", json=payload, headers=_auth(client))

    assert response.status_code == 422
    assert response.json()["detail"] == [
        {"path": "1.unexpected", "message": "Extra inputs are not permitted"}
    ]
    assert client.get("/api/offers", params={"limit": 100}).json()["total"] == 42


def test_manual_import_api_enforces_count_and_byte_limits(client):
    too_many = [_manual_offer_payload(external_id=f"manual-{index}") for index in range(501)]
    count_response = client.post("/api/import", json=too_many, headers=_auth(client))
    oversized = b"[" + b" " * (2 * 1024 * 1024) + b"]"
    size_response = client.post(
        "/api/import",
        content=oversized,
        headers={**_auth(client), "Content-Type": "application/json"},
    )

    assert count_response.status_code == 422
    assert "500" in count_response.text
    assert size_response.status_code == 413
    assert "2 MiB" in size_response.text


def test_feedback_and_saved_views_are_persisted_with_authorization(client):
    offer_id = _offer_id(client, "demo-001")
    feedback = client.post(
        f"/api/offers/{offer_id}/feedback",
        json={"value": "relevant", "note": "Strong match"},
        headers=_auth(client),
    )
    saved = client.post(
        "/api/saved-views",
        json={"name": "Top matches", "filters": {"score_min": 80}},
        headers=_auth(client),
    )
    assert feedback.status_code == 201
    assert feedback.json()["offer_id"] == offer_id
    assert saved.status_code == 201
    assert client.get("/api/saved-views").json() == [saved.json()]
    deleted = client.delete(
        f"/api/saved-views/{saved.json()['id']}", headers=_auth(client)
    )
    assert deleted.status_code == 204


def test_config_validation_does_not_write_and_authorized_update_does(client):
    original = client.get("/api/config").json()
    invalid = original | {"unknown": "must be rejected"}
    validation = client.post("/api/config/validate", json=invalid)
    assert validation.status_code == 200
    assert validation.json()["valid"] is False
    assert validation.json()["errors"][0]["path"] == "unknown"
    assert client.get("/api/config").json() == original
    updated = {
        **original,
        "profile": {**original["profile"], "roles": ["Data Analyst"]},
    }
    response = client.put("/api/config", json=updated, headers=_auth(client))
    assert response.status_code == 200
    assert client.get("/api/config").json()["profile"]["roles"] == ["Data Analyst"]


def test_config_is_rejected_for_non_loopback_clients(tmp_path):
    config_dir = tmp_path / "config"
    initialize_config(config_dir)
    application = create_app(ApiSettings(data_dir=tmp_path, config_dir=config_dir))
    with TestClient(application, client=("203.0.113.20", 50000)) as remote_client:
        assert remote_client.get("/health").status_code == 200
        assert remote_client.get("/api/config").status_code == 403


def test_session_bootstrap_requires_loopback_or_explicit_testclient_mode(tmp_path):
    config_dir = tmp_path / "config"
    initialize_config(config_dir)
    production_app = create_app(ApiSettings(data_dir=tmp_path, config_dir=config_dir))

    with TestClient(production_app) as implicit_test_client:
        forbidden = implicit_test_client.get("/api/session")
        assert forbidden.status_code == 403
        assert production_app.state.session_token not in forbidden.text

    loopback_app = create_app(ApiSettings(data_dir=tmp_path, config_dir=config_dir))
    with TestClient(loopback_app, client=("127.0.0.1", 50000)) as loopback_client:
        response = loopback_client.get("/api/session")
        assert response.status_code == 200
        assert response.json() == {"token": loopback_app.state.session_token}
        assert response.headers["cache-control"] == "no-store, no-cache"
        assert response.headers["pragma"] == "no-cache"

    test_app = create_app(
        ApiSettings(data_dir=tmp_path, config_dir=config_dir, allow_testclient=True)
    )
    with TestClient(test_app) as explicit_test_client:
        assert explicit_test_client.get("/api/session").json() == {
            "token": test_app.state.session_token
        }
    with TestClient(
        test_app, client=("203.0.113.20", 50000)
    ) as remote_test_client:
        forbidden = remote_test_client.get("/api/session")
        assert forbidden.status_code == 403
        assert test_app.state.session_token not in forbidden.text


def test_session_bootstrap_is_absent_from_openapi(tmp_path):
    config_dir = tmp_path / "config"
    initialize_config(config_dir)
    application = create_app(ApiSettings(data_dir=tmp_path, config_dir=config_dir))

    schema = application.openapi()

    assert "/api/session" not in schema["paths"]
    assert all(
        "session" not in name.casefold() and "token" not in name.casefold()
        for name in schema["components"]["schemas"]
    )
    assert application.state.session_token not in str(schema)


def test_session_token_file_is_private_and_removed_after_shutdown(tmp_path):
    config_dir = tmp_path / "config"
    initialize_config(config_dir)
    application = create_app(ApiSettings(data_dir=tmp_path, config_dir=config_dir))
    with TestClient(application):
        token_path = application.state.session_token_path
        assert token_path.read_text(encoding="utf-8") == application.state.session_token
        assert stat.S_IMODE(token_path.stat().st_mode) == 0o600
    assert not token_path.exists()


def test_market_insights_and_sources_are_derived_from_local_state(client):
    insights = client.get("/api/insights/market").json()
    sources = client.get("/api/sources").json()
    assert insights["total_offers"] == 42
    assert insights["decisions"] == {
        "monitor": 10,
        "prioritize": 10,
        "reject": 10,
        "review": 12,
    }
    assert insights["skills"][0]["count"] > 1
    assert {source["name"] for source in sources} >= {"linkedin", "indeed", "wttj"}


def test_configured_remote_sources_are_unavailable_without_delivered_connectors(client):
    payload = client.get("/api/config").json()
    payload["sources"]["sources"].update(
        {
            "adzuna": {"mode": "api", "enabled": True, "quota_per_day": 25},
            "public_ats": {"mode": "ats", "enabled": True, "quota_per_day": 50},
        }
    )

    written = client.put("/api/config", json=payload, headers=_auth(client))
    sources = {
        source["name"]: source for source in client.get("/api/sources").json()
    }

    assert written.status_code == 200
    for name in ("local_demo", "adzuna", "public_ats"):
        assert sources[name]["available"] is False
        assert sources[name]["automated"] is False
    assert sources["adzuna"]["quota_per_day"] == 25
    assert sources["public_ats"]["quota_per_day"] == 50


def test_market_insights_count_only_offers_visible_in_the_active_radar(client):
    offer_id = _offer_id(client, "demo-001")
    with sqlite3.connect(client.app.state.store.path) as connection:
        connection.execute(
            "UPDATE offers SET status = 'inactive' WHERE id = ?", (offer_id,)
        )

    radar = client.get("/api/offers", params={"limit": 100}).json()
    insights = client.get("/api/insights/market").json()

    assert radar["total"] == 41
    assert insights["total_offers"] == radar["total"]


def test_rescore_updates_score_without_reactivating_an_inactive_offer(client):
    offer_id = _offer_id(client, "demo-001")
    with sqlite3.connect(client.app.state.store.path) as connection:
        connection.execute(
            "UPDATE offers SET status = 'inactive' WHERE id = ?", (offer_id,)
        )
        connection.execute(
            "UPDATE offer_scores SET score_version = 'stale' WHERE offer_id = ?",
            (offer_id,),
        )

    response = client.post("/api/rescore", headers=_auth(client))

    with sqlite3.connect(client.app.state.store.path) as connection:
        status, score_version = connection.execute(
            "SELECT o.status, s.score_version FROM offers o "
            "JOIN offer_scores s ON s.offer_id = o.id WHERE o.id = ?",
            (offer_id,),
        ).fetchone()
    radar = client.get("/api/offers", params={"limit": 100}).json()
    insights = client.get("/api/insights/market").json()

    assert response.status_code == 200
    assert status == "inactive"
    assert score_version != "stale"
    assert radar["total"] == insights["total_offers"] == 41


def test_normalized_custom_source_key_is_used_for_health(client):
    payload = client.get("/api/config").json()
    payload["sources"]["sources"][" ÉCOLE  ATS "] = {"mode": "api"}

    written = client.put("/api/config", json=payload, headers=_auth(client))
    refreshed = client.post(
        "/api/refresh",
        json={"sources": ["école ats"]},
        headers=_auth(client),
    )
    sources = {
        source["name"]: source for source in client.get("/api/sources").json()
    }

    assert written.status_code == 200
    assert "école ats" in written.json()["sources"]["sources"]
    assert refreshed.status_code == 200
    assert refreshed.json()["skipped_sources"] == ["école ats"]
    assert sources["école ats"]["health_status"] == "skipped"


def test_source_health_duplicates_merge_to_fresh_status_and_latest_success(client):
    with sqlite3.connect(client.app.state.store.path) as connection:
        connection.execute(
            "INSERT OR REPLACE INTO source_health "
            "(source, status, last_success_at, quota_remaining, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                "local_demo",
                "failed",
                "2026-08-19T08:00:00+00:00",
                3,
                "2026-08-20T08:00:00+00:00",
            ),
        )
        connection.execute(
            "INSERT INTO source_health "
            "(source, status, last_success_at, quota_remaining, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                "LOCAL_DEMO",
                "ok",
                "2026-08-25T08:00:00+00:00",
                8,
                "2026-08-25T08:00:00+00:00",
            ),
        )

    refreshed = client.post(
        "/api/refresh", json={"sources": ["local_demo"]}, headers=_auth(client)
    )
    sources = {
        source["name"]: source for source in client.get("/api/sources").json()
    }
    with sqlite3.connect(client.app.state.store.path) as connection:
        rows = connection.execute(
            "SELECT source, status, last_success_at, updated_at "
            "FROM source_health WHERE lower(source) = 'local_demo'"
        ).fetchall()

    assert refreshed.status_code == 200
    assert sources["local_demo"]["health_status"] == "skipped"
    assert sources["local_demo"]["last_success_at"] == "2026-08-25T08:00:00Z"
    assert rows == [
        (
            "local_demo",
            "skipped",
            "2026-08-25T08:00:00+00:00",
            FIXED_NOW.isoformat(),
        )
    ]


def test_sources_include_stored_imports_absent_from_the_current_offer_page(client):
    payload = _manual_offer_payload(
        external_id="community-001",
        source="Community Board",
        url="https://community.example/jobs/community-001",
    )
    imported = client.post("/api/import", json=[payload], headers=_auth(client))
    with sqlite3.connect(client.app.state.store.path) as connection:
        connection.execute(
            "UPDATE offers SET status = 'inactive' WHERE id = ("
            "SELECT offer_id FROM offer_sources WHERE source = 'community board'"
            ")"
        )

    page = client.get("/api/offers", params={"q": "community-001"}).json()
    sources = {
        source["name"]: source for source in client.get("/api/sources").json()
    }

    assert imported.status_code == 200
    assert page["total"] == 0
    assert sources["community board"] == {
        "name": "community board",
        "mode": "stored",
        "enabled": False,
        "available": False,
        "automated": False,
        "quota_per_day": 0,
        "credential_configured": True,
        "health_status": "not_run",
        "last_success_at": None,
        "quota_remaining": None,
    }


def test_rescore_repairs_historical_source_identity_without_duplicates(client):
    store = client.app.state.store
    offer_id = _offer_id(client, "demo-001")
    with sqlite3.connect(store.path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        row = connection.execute(
            "SELECT fingerprint, raw_payload_json FROM offer_sources "
            "WHERE offer_id = ? AND external_id = 'demo-001'",
            (offer_id,),
        ).fetchone()
        payload = json.loads(row[1])
        payload["source"] = "LOCAL_DEMO"
        connection.execute(
            "UPDATE offer_sources SET source = ?, fingerprint = ?, raw_payload_json = ? "
            "WHERE offer_id = ? AND external_id = 'demo-001'",
            (
                "LOCAL_DEMO",
                "LOCAL_DEMO:demo-001",
                json.dumps(payload, sort_keys=True),
                offer_id,
            ),
        )

    first = client.post("/api/rescore", headers=_auth(client))
    second = client.post("/api/rescore", headers=_auth(client))
    filtered = client.get(
        "/api/offers",
        params={"source": "LOCAL_DEMO", "q": "demo-001", "limit": 100},
    ).json()
    with sqlite3.connect(store.path) as connection:
        identities = connection.execute(
            "SELECT source, external_id FROM offer_sources "
            "WHERE external_id = 'demo-001'"
        ).fetchall()

    assert first.status_code == second.status_code == 200
    assert identities == [("local_demo", "demo-001")]
    assert filtered["total"] == 1


def test_rescore_quarantines_historical_invalid_url_without_losing_the_row(client):
    store = client.app.state.store
    offer_id = _offer_id(client, "demo-001")
    dangerous_url = "javascript:alert(document.domain)"
    with sqlite3.connect(store.path) as connection:
        row = connection.execute(
            "SELECT raw_payload_json FROM offer_sources "
            "WHERE offer_id = ? AND external_id = 'demo-001'",
            (offer_id,),
        ).fetchone()
        payload = json.loads(row[0])
        payload["url"] = dangerous_url
        connection.execute(
            "UPDATE offer_sources SET source_url = ?, raw_payload_json = ? "
            "WHERE offer_id = ? AND external_id = 'demo-001'",
            (dangerous_url, json.dumps(payload, sort_keys=True), offer_id),
        )

    result = routes.rescore_store(
        store,
        load_config(client.app.state.settings.config_dir),
        now=FIXED_NOW,
    )
    with sqlite3.connect(store.path) as connection:
        row = connection.execute(
            "SELECT source_url, raw_payload_json FROM offer_sources "
            "WHERE offer_id = ? AND external_id = 'demo-001'",
            (offer_id,),
        ).fetchone()
        count = connection.execute(
            "SELECT COUNT(*) FROM offer_sources WHERE offer_id = ?",
            (offer_id,),
        ).fetchone()[0]
    quarantined = json.loads(row[1])
    page = client.get("/api/offers", params={"q": "demo-001"}).json()

    assert result.offers_scored == 41
    assert count == 1
    assert row[0] == ""
    assert quarantined["_quarantine_reason"] == "invalid_url"
    assert quarantined["_quarantined_url"] == dangerous_url
    assert quarantined["url"] == ""
    assert page["total"] == 0


def test_refresh_status_and_rescore_report_local_operations(client):
    refresh = client.post(
        "/api/refresh", json={"sources": ["local_demo"]}, headers=_auth(client)
    )
    rescore = client.post("/api/rescore", headers=_auth(client))
    assert refresh.status_code == 200
    assert refresh.json()["status"] == "completed"
    assert refresh.json()["skipped_sources"] == ["local_demo"]
    assert client.get("/api/refresh/status").json()[0]["status"] == "completed"
    assert rescore.json()["offers_scored"] == 42


def test_skipped_refresh_preserves_last_success_at(client):
    previous_success = "2026-08-20T08:00:00+00:00"
    with sqlite3.connect(client.app.state.store.path) as connection:
        connection.execute(
            "INSERT OR REPLACE INTO source_health "
            "(source, status, last_success_at, updated_at) VALUES (?, ?, ?, ?)",
            ("local_demo", "ok", previous_success, previous_success),
        )

    response = client.post(
        "/api/refresh", json={"sources": ["local_demo"]}, headers=_auth(client)
    )

    assert response.status_code == 200
    with sqlite3.connect(client.app.state.store.path) as connection:
        assert connection.execute(
            "SELECT status, last_success_at FROM source_health WHERE source = ?",
            ("local_demo",),
        ).fetchone() == ("skipped", previous_success)


def test_failed_refresh_preserves_last_success_at(client, monkeypatch):
    previous_success = "2026-08-20T08:00:00+00:00"
    with sqlite3.connect(client.app.state.store.path) as connection:
        connection.execute(
            "INSERT OR REPLACE INTO source_health "
            "(source, status, last_success_at, updated_at) VALUES (?, ?, ?, ?)",
            ("local_demo", "ok", previous_success, previous_success),
        )

    def fail_refresh(**kwargs):
        del kwargs
        raise RuntimeError("connector failed")

    monkeypatch.setattr(routes, "run_refresh", fail_refresh)
    response = client.post(
        "/api/refresh", json={"sources": ["local_demo"]}, headers=_auth(client)
    )

    assert response.status_code == 500
    with sqlite3.connect(client.app.state.store.path) as connection:
        assert connection.execute(
            "SELECT status, last_success_at FROM source_health WHERE source = ?",
            ("local_demo",),
        ).fetchone() == ("failed", previous_success)


def test_refresh_failure_is_finalized_and_public_error_is_sanitized(
    client, monkeypatch
):
    fake_secret = "connector-secret-must-not-escape"

    def fail_refresh(**kwargs):
        del kwargs
        raise RuntimeError(fake_secret)

    monkeypatch.setattr(routes, "run_refresh", fail_refresh)
    response = client.post(
        "/api/refresh", json={"sources": ["local_demo"]}, headers=_auth(client)
    )
    assert response.status_code == 500
    assert response.json() == {"detail": "Refresh failed"}
    assert fake_secret not in response.text
    status_payload = client.get("/api/refresh/status").json()[0]
    assert status_payload["status"] == "failed"
    assert status_payload["finished_at"] is not None
    assert status_payload["error_summary"] == "Refresh failed"


def test_unknown_offer_and_bad_token_return_public_errors(client):
    missing = client.get("/api/offers/999999")
    unauthorized = client.post(
        "/api/rescore", headers={"X-Job-Radar-Token": "not-the-token"}
    )
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Offer not found"}
    assert unauthorized.status_code == 401
    assert "token" not in unauthorized.text.casefold()
