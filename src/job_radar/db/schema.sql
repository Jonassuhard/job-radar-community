-- Local-only SQLite schema. Timestamps are ISO 8601 UTC strings.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS offers (
    id INTEGER PRIMARY KEY,
    canonical_key TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT NOT NULL,
    contract TEXT NOT NULL,
    remote TEXT NOT NULL,
    description TEXT NOT NULL,
    published_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active'
);

CREATE INDEX IF NOT EXISTS idx_offers_published_at ON offers(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_offers_status ON offers(status);

CREATE TABLE IF NOT EXISTS offer_sources (
    id INTEGER PRIMARY KEY,
    offer_id INTEGER NOT NULL REFERENCES offers(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    source_url TEXT NOT NULL,
    fingerprint TEXT NOT NULL UNIQUE,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    raw_payload_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(source, external_id)
);

CREATE INDEX IF NOT EXISTS idx_offer_sources_offer_id ON offer_sources(offer_id);
CREATE INDEX IF NOT EXISTS idx_offer_sources_source_seen ON offer_sources(source, last_seen_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_offer_sources_offer_fingerprint
    ON offer_sources(offer_id, fingerprint);

CREATE TABLE IF NOT EXISTS offer_facts (
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
);

CREATE INDEX IF NOT EXISTS idx_offer_facts_offer_id ON offer_facts(offer_id);
CREATE INDEX IF NOT EXISTS idx_offer_facts_name_value ON offer_facts(name, value);
CREATE INDEX IF NOT EXISTS idx_offer_facts_provenance ON offer_facts(source_fingerprint);

CREATE TABLE IF NOT EXISTS offer_scores (
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
);

CREATE INDEX IF NOT EXISTS idx_offer_scores_decision_rank ON offer_scores(decision, relevance DESC);
CREATE INDEX IF NOT EXISTS idx_offer_scores_profile_rank ON offer_scores(profile_id, relevance DESC);

CREATE TABLE IF NOT EXISTS refresh_runs (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    offers_seen INTEGER NOT NULL DEFAULT 0,
    offers_saved INTEGER NOT NULL DEFAULT 0,
    error_summary TEXT
);

CREATE INDEX IF NOT EXISTS idx_refresh_runs_source_started ON refresh_runs(source, started_at DESC);

CREATE TABLE IF NOT EXISTS source_health (
    source TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    last_success_at TEXT,
    quota_remaining INTEGER,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_feedback (
    id INTEGER PRIMARY KEY,
    offer_id INTEGER NOT NULL REFERENCES offers(id) ON DELETE CASCADE,
    value TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_user_feedback_offer_id ON user_feedback(offer_id, created_at DESC);

CREATE TABLE IF NOT EXISTS saved_views (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    filters_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS http_cache (
    cache_key TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    response_status INTEGER NOT NULL,
    response_body TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_http_cache_expiry ON http_cache(expires_at);

PRAGMA user_version = 2;
