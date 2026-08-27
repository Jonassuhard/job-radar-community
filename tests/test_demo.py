from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from job_radar.api.routes import rescore_store
from job_radar.config.loader import initialize_config, load_config
from job_radar.db.store import RadarStore
from job_radar.demo import seed_demo

FIXED_NOW = datetime(2026, 8, 26, 9, 30, tzinfo=UTC)


def test_seed_is_deterministic(tmp_path):
    first = RadarStore(tmp_path / "one.db")
    second = RadarStore(tmp_path / "two.db")

    assert seed_demo(first, FIXED_NOW) == seed_demo(second, FIXED_NOW) == 42
    first_materialization = [item.model_dump(mode="json") for item in first.list_scored_offers()]
    second_materialization = [item.model_dump(mode="json") for item in second.list_scored_offers()]
    assert first_materialization == second_materialization

    assert seed_demo(first, FIXED_NOW) == 42
    assert [item.model_dump(mode="json") for item in first.list_scored_offers()] == first_materialization
    assert _row_counts(first.path) == {
        "offer_facts": 84,
        "offer_scores": 42,
        "offer_sources": 42,
        "offers": 42,
    }


def test_demo_uses_only_fictitious_urls_and_dates_derived_from_the_clock(tmp_path):
    store = RadarStore(tmp_path / "radar.db")

    seed_demo(store, FIXED_NOW)
    offers = store.list_scored_offers()

    assert len(offers) == 42
    assert {item.decision for item in offers} == {"prioritize", "review", "monitor", "reject"}
    assert all(item.offer.url.endswith(".example") or ".example/" in item.offer.url for item in offers)
    assert all(item.offer.published_at <= FIXED_NOW for item in offers)
    assert {FIXED_NOW - item.offer.published_at for item in offers} >= {
        timedelta(days=0),
        timedelta(days=1),
        timedelta(days=7),
        timedelta(days=30),
    }


def test_demo_covers_sources_contracts_places_and_blocked_offers(tmp_path):
    store = RadarStore(tmp_path / "radar.db")

    seed_demo(store, FIXED_NOW)
    offers = store.list_scored_offers()

    assert {item.offer.source for item in offers} == {
        "adzuna",
        "france_travail",
        "jooble",
        "public_ats",
        "remotive",
    }
    assert {item.offer.contract for item in offers} >= {
        "apprenticeship",
        "contract",
        "fixed_term",
        "permanent",
    }
    assert len({item.offer.location for item in offers}) >= 4
    assert any(item.blocker is not None for item in offers)


def test_demo_rescore_keeps_all_public_decisions_usable(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    initialize_config(config_dir)
    store = RadarStore(tmp_path / "radar.db")
    seed_demo(store, FIXED_NOW)

    result = rescore_store(store, load_config(config_dir), now=FIXED_NOW)
    rescored = store.list_scored_offers()

    assert result.offers_scored == 42
    assert {offer.decision for offer in rescored} == {
        "reject",
        "monitor",
        "review",
        "prioritize",
    }
    assert all(offer.score_version == result.score_version for offer in rescored)


def test_built_wheel_seeds_demo_outside_the_checkout(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    wheel_dir = tmp_path / "wheel"
    venv_dir = tmp_path / "venv"
    run_dir = tmp_path / "run"
    wheel_command = [
        sys.executable,
        "-m",
        "pip",
        "wheel",
        "--no-deps",
        "--wheel-dir",
        str(wheel_dir),
        str(project_root),
    ]
    subprocess.run(wheel_command, check=True, capture_output=True, text=True)
    subprocess.run([sys.executable, "-m", "venv", "--system-site-packages", str(venv_dir)], check=True)
    wheel = next(wheel_dir.glob("job_radar_community-*.whl"))
    python = venv_dir / "bin" / "python"
    subprocess.run([str(python), "-m", "pip", "install", "--no-deps", str(wheel)], check=True)
    run_dir.mkdir()
    command = [
        str(python),
        "-c",
        (
            "from datetime import UTC, datetime; from pathlib import Path; "
            "from job_radar.db.store import RadarStore; from job_radar.demo import seed_demo; "
            "print(seed_demo(RadarStore(Path('demo.db')), datetime(2026, 8, 26, 9, 30, tzinfo=UTC)))"
        ),
    ]
    environment = os.environ | {"PYTHONPATH": ""}

    result = subprocess.run(
        command,
        check=False,
        cwd=run_dir,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "42"


def _row_counts(path: Path) -> dict[str, int]:
    import sqlite3

    with sqlite3.connect(path) as connection:
        return {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("offers", "offer_sources", "offer_facts", "offer_scores")
        }
