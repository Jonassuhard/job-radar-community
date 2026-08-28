from __future__ import annotations

import json
import os
import sqlite3
import stat
import subprocess
import sys
from importlib.metadata import requires
from pathlib import Path

import pytest
from typer.testing import CliRunner

from job_radar.api import routes
from job_radar.cli import app
from job_radar.config.loader import initialize_config

runner = CliRunner()


def _manual_offer_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "external_id": "manual-cli-001",
        "source": "linkedin",
        "url": "https://www.linkedin.com/jobs/view/manual-cli-001",
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


def test_runtime_package_installs_the_server_required_by_serve_command():
    dependencies = requires("job-radar-community") or []
    assert any(
        dependency.casefold().startswith("uvicorn") for dependency in dependencies
    )


def test_demo_command_creates_runnable_database(tmp_path):
    result = runner.invoke(app, ["demo", "--data-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    with sqlite3.connect(tmp_path / "job-radar.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM offers").fetchone()[0] == 42
    assert (tmp_path / "config" / "profile.yml").exists()


def test_init_is_safe_to_rerun_without_replacing_config(tmp_path):
    first = runner.invoke(app, ["init", "--data-dir", str(tmp_path)])
    profile = tmp_path / "config" / "profile.yml"
    profile.write_text(
        "roles: []\nskills: []\nevidence: []\nlanguages: []\nseniority: custom\n"
    )
    second = runner.invoke(app, ["init", "--data-dir", str(tmp_path)])
    assert first.exit_code == second.exit_code == 0
    assert "seniority: custom" in profile.read_text()


def test_config_validate_reports_paths_and_never_modifies_files(tmp_path):
    assert runner.invoke(app, ["init", "--data-dir", str(tmp_path)]).exit_code == 0
    profile = tmp_path / "config" / "profile.yml"
    profile.write_text("roles: unexpected\n")
    result = runner.invoke(
        app, ["config", "validate", "--config-dir", str(tmp_path / "config")]
    )
    assert result.exit_code == 1
    assert "profile.roles" in result.output
    assert profile.read_text() == "roles: unexpected\n"


def test_doctor_checks_existing_database_without_printing_secret_values(
    tmp_path, monkeypatch
):
    assert runner.invoke(app, ["init", "--data-dir", str(tmp_path)]).exit_code == 0
    monkeypatch.setenv("JOB_RADAR_DEMO_API_KEY", "never-print-this-value")
    result = runner.invoke(app, ["doctor", "--data-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "never-print-this-value" not in result.output
    assert "schema" in result.output.casefold()
    assert "manual_only" in result.output
    assert "Source local_demo: unavailable in this version" in result.output
    assert "Source local_demo: ready" not in result.output


@pytest.mark.parametrize(
    ("target", "expected"),
    [("data", "0700"), ("database", "0600")],
)
def test_doctor_rejects_permissive_runtime_paths(tmp_path, target, expected):
    assert runner.invoke(app, ["init", "--data-dir", str(tmp_path)]).exit_code == 0
    path = tmp_path if target == "data" else tmp_path / "job-radar.db"
    path.chmod(0o755 if target == "data" else 0o644)

    result = runner.invoke(app, ["doctor", "--data-dir", str(tmp_path)])

    assert result.exit_code != 0
    assert expected in result.output
    assert stat.S_IMODE(path.lstat().st_mode) == (0o755 if target == "data" else 0o644)


def test_doctor_rejects_symlinked_database_without_following_it(tmp_path):
    assert runner.invoke(app, ["init", "--data-dir", str(tmp_path)]).exit_code == 0
    database = tmp_path / "job-radar.db"
    target = tmp_path / "database-target.db"
    database.replace(target)
    database.symlink_to(target)

    result = runner.invoke(app, ["doctor", "--data-dir", str(tmp_path)])

    assert result.exit_code != 0
    assert "symbolic links are refused" in result.output
    assert database.is_symlink()


def test_doctor_does_not_create_a_missing_database(tmp_path):
    initialize_config(tmp_path / "config")
    database = tmp_path / "job-radar.db"
    result = runner.invoke(app, ["doctor", "--data-dir", str(tmp_path)])
    assert result.exit_code != 0
    assert "missing" in result.output.casefold()
    assert not database.exists()


def test_doctor_does_not_rewrite_a_corrupt_database(tmp_path):
    initialize_config(tmp_path / "config")
    database = tmp_path / "job-radar.db"
    database.write_bytes(b"not a sqlite database")
    database.chmod(0o600)
    before = database.read_bytes()
    result = runner.invoke(app, ["doctor", "--data-dir", str(tmp_path)])
    assert result.exit_code != 0
    assert "corrupt" in result.output.casefold()
    assert database.read_bytes() == before


@pytest.mark.parametrize(
    "missing_table",
    [
        "offers",
        "offer_sources",
        "offer_facts",
        "offer_scores",
        "refresh_runs",
        "source_health",
        "user_feedback",
        "saved_views",
        "http_cache",
    ],
)
def test_doctor_rejects_each_incomplete_public_schema_without_modifying_it(
    tmp_path, missing_table
):
    assert runner.invoke(app, ["init", "--data-dir", str(tmp_path)]).exit_code == 0
    database = tmp_path / "job-radar.db"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute(f"DROP TABLE {missing_table}")
    before = database.read_bytes()

    result = runner.invoke(app, ["doctor", "--data-dir", str(tmp_path)])

    assert result.exit_code != 0
    assert "incomplete" in result.output.casefold()
    assert database.read_bytes() == before


def test_refresh_and_rescore_commands_run_without_network_keys(tmp_path):
    assert runner.invoke(app, ["demo", "--data-dir", str(tmp_path)]).exit_code == 0
    refresh = runner.invoke(app, ["refresh", "--data-dir", str(tmp_path)])
    rescore = runner.invoke(app, ["rescore", "--data-dir", str(tmp_path)])
    assert refresh.exit_code == 0, refresh.output
    assert "skipped" in refresh.output.casefold()
    assert rescore.exit_code == 0, rescore.output
    assert "42" in rescore.output


def test_import_command_previews_then_imports_a_local_json_file(tmp_path):
    assert runner.invoke(app, ["init", "--data-dir", str(tmp_path)]).exit_code == 0
    source_file = tmp_path / "offers.json"
    source_file.write_text(json.dumps([_manual_offer_payload()]), encoding="utf-8")

    preview = runner.invoke(
        app, ["import", str(source_file), "--preview", "--data-dir", str(tmp_path)]
    )
    with sqlite3.connect(tmp_path / "job-radar.db") as connection:
        count_after_preview = connection.execute("SELECT COUNT(*) FROM offers").fetchone()[0]
    imported = runner.invoke(
        app, ["import", str(source_file), "--data-dir", str(tmp_path)]
    )
    with sqlite3.connect(tmp_path / "job-radar.db") as connection:
        count_after_import = connection.execute("SELECT COUNT(*) FROM offers").fetchone()[0]

    assert preview.exit_code == 0, preview.output
    assert "Preview" in preview.output
    assert count_after_preview == 0
    assert imported.exit_code == 0, imported.output
    assert "1 saved" in imported.output
    assert count_after_import == 1


def test_import_command_reports_indexed_validation_errors(tmp_path):
    assert runner.invoke(app, ["init", "--data-dir", str(tmp_path)]).exit_code == 0
    source_file = tmp_path / "offers.json"
    source_file.write_text(
        json.dumps([_manual_offer_payload(unexpected=True)]), encoding="utf-8"
    )

    result = runner.invoke(
        app, ["import", str(source_file), "--data-dir", str(tmp_path)]
    )

    assert result.exit_code == 1
    assert "0.unexpected" in result.output
    with sqlite3.connect(tmp_path / "job-radar.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM offers").fetchone()[0] == 0


def test_refresh_failure_is_sanitized_in_cli_and_database(tmp_path, monkeypatch):
    assert runner.invoke(app, ["demo", "--data-dir", str(tmp_path)]).exit_code == 0
    fake_secret = "cli-connector-secret"

    def fail_refresh(**kwargs):
        del kwargs
        raise RuntimeError(fake_secret)

    monkeypatch.setattr(routes, "run_refresh", fail_refresh)
    result = runner.invoke(app, ["refresh", "--data-dir", str(tmp_path)])
    assert result.exit_code == 1
    assert "Refresh failed" in result.output
    assert fake_secret not in result.output
    with sqlite3.connect(tmp_path / "job-radar.db") as connection:
        assert connection.execute(
            "SELECT status, error_summary FROM refresh_runs ORDER BY id DESC LIMIT 1"
        ).fetchone() == ("failed", "Refresh failed")


def test_serve_refuses_non_loopback_without_creating_runtime(tmp_path):
    result = runner.invoke(
        app, ["serve", "--host", "0.0.0.0", "--data-dir", str(tmp_path)]
    )
    assert result.exit_code != 0
    assert "loopback" in result.output.casefold()
    assert "token" not in result.output.casefold()
    assert not (tmp_path / "job-radar.db").exists()


def test_serve_never_prints_session_token(tmp_path, monkeypatch):
    initialize_config(tmp_path / "config")
    captured = {}

    def fake_run(application, **kwargs):
        captured["token"] = application.state.session_token
        captured["kwargs"] = kwargs

    monkeypatch.setattr("uvicorn.run", fake_run)
    result = runner.invoke(app, ["serve", "--data-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert captured["token"] not in result.output
    assert "token" not in result.output.casefold()
    assert captured["kwargs"]["host"] == "127.0.0.1"


def test_serve_creates_an_absent_runtime_with_private_permissions(
    tmp_path, monkeypatch
):
    runtime = tmp_path / "runtime"
    monkeypatch.setattr("uvicorn.run", lambda application, **kwargs: None)
    previous_umask = os.umask(0)
    try:
        result = runner.invoke(app, ["serve", "--data-dir", str(runtime)])
    finally:
        os.umask(previous_umask)

    assert result.exit_code == 0, result.output
    assert stat.S_IMODE(runtime.stat().st_mode) == 0o700
    assert stat.S_IMODE((runtime / "job-radar.db").stat().st_mode) == 0o600


def test_init_refuses_a_permissive_directory_with_actionable_remediation(tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o755)

    result = runner.invoke(app, ["init", "--data-dir", str(runtime)])

    assert result.exit_code == 2
    assert "chmod 700" in result.output
    assert str(runtime) in result.output
    assert stat.S_IMODE(runtime.stat().st_mode) == 0o755
    assert not (runtime / "job-radar.db").exists()


def test_installed_wheel_cli_runs_all_local_commands_with_empty_pythonpath(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    wheel_dir = tmp_path / "wheel"
    venv_dir = tmp_path / "venv"
    run_dir = tmp_path / "outside-checkout"
    wheel_dir.mkdir()
    run_dir.mkdir()
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--wheel-dir",
            str(wheel_dir),
            str(project_root),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)
    wheel = next(wheel_dir.glob("job_radar_community-*.whl"))
    subprocess.run(
        [
            str(venv_dir / "bin" / "python"),
            "-m",
            "pip",
            "install",
            str(wheel),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    executable = venv_dir / "bin" / "job-radar"
    data_dir = run_dir / "data"
    environment = os.environ | {"PYTHONPATH": ""}
    for command in ("init", "demo", "doctor", "refresh", "rescore"):
        result = subprocess.run(
            [str(executable), command, "--data-dir", str(data_dir)],
            cwd=run_dir,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, f"{command}: {result.stdout}\n{result.stderr}"
