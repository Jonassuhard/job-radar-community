"""Command-line entry point for the local Job Radar runtime."""

from __future__ import annotations

import ipaddress
import os
import sqlite3
import stat
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from job_radar.api.app import ApiSettings, create_app
from job_radar.api.routes import (
    RefreshExecutionError,
    refresh_store,
    rescore_store,
)
from job_radar.config.defaults import default_config_dir
from job_radar.config.loader import ConfigError, initialize_config, load_config
from job_radar.connectors import remote_connector_available
from job_radar.db.migrations import CURRENT_SCHEMA_VERSION, PUBLIC_TABLE_NAMES
from job_radar.db.store import RadarStore
from job_radar.demo import seed_demo
from job_radar.importing import OfferImportError, parse_offer_import
from job_radar.local_security import PrivatePathError
from job_radar.pipeline.refresh import import_offers

app = typer.Typer(add_completion=False, help="Job Radar local command-line interface.")
config_app = typer.Typer(
    add_completion=False, help="Validate local YAML configuration."
)
app.add_typer(config_app, name="config")

DataDirectory = Annotated[
    Path | None,
    typer.Option(help="Directory for the local SQLite database."),
]
ConfigDirectory = Annotated[
    Path | None,
    typer.Option(help="Directory for local YAML configuration."),
]
ImportFile = Annotated[
    Path,
    typer.Argument(
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="Local JSON file containing an array of offers.",
    ),
]


def _default_data_dir() -> Path:
    return Path(
        os.environ.get(
            "JOB_RADAR_DATA_DIR", Path.home() / ".local" / "share" / "job-radar"
        )
    ).expanduser()


def _paths(data_dir: Path | None, config_dir: Path | None) -> tuple[Path, Path]:
    resolved_data = (data_dir or _default_data_dir()).expanduser()
    resolved_config = (
        config_dir
        or (resolved_data / "config" if data_dir is not None else default_config_dir())
    ).expanduser()
    return resolved_data, resolved_config


def _runtime(data_dir: Path | None, config_dir: Path | None) -> tuple[RadarStore, Path]:
    resolved_data, resolved_config = _paths(data_dir, config_dir)
    try:
        store = RadarStore(resolved_data / "job-radar.db")
    except PrivatePathError as error:
        _fail_private_path(resolved_data, error)
    return store, resolved_config


def _fail_private_path(path: Path, error: Exception) -> None:
    typer.echo(
        f"Unsafe local path: {path}. {error}. Use a dedicated directory; "
        "run chmod 700 on the directory and chmod 600 on existing Job Radar files.",
        err=True,
    )
    raise typer.Exit(2)


@app.callback()
def main() -> None:
    """Inspect and refresh a private, local job radar."""


@app.command("init")
def initialize(
    data_dir: DataDirectory = None,
    config_dir: ConfigDirectory = None,
) -> None:
    """Create missing configuration and the local database."""

    store, resolved_config = _runtime(data_dir, config_dir)
    try:
        created = initialize_config(resolved_config)
    except ConfigError as error:
        _fail_private_path(resolved_config, error)
    typer.echo(f"Database ready: {store.path}")
    typer.echo(f"Configuration ready: {resolved_config} ({len(created)} files created)")


@app.command()
def demo(
    data_dir: DataDirectory = None,
    config_dir: ConfigDirectory = None,
) -> None:
    """Create a runnable offline database with 42 fictitious offers."""

    store, resolved_config = _runtime(data_dir, config_dir)
    try:
        initialize_config(resolved_config)
    except ConfigError as error:
        _fail_private_path(resolved_config, error)
    count = seed_demo(store, datetime.now(UTC))
    typer.echo(f"Demo ready: {count} fictitious offers in {store.path}")


@config_app.command("validate")
def validate_configuration(
    config_dir: ConfigDirectory = None,
) -> None:
    """Validate every YAML file without modifying it."""

    try:
        load_config((config_dir or default_config_dir()).expanduser())
    except ConfigError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error
    typer.echo("Configuration valid")


@app.command()
def refresh(
    source: Annotated[
        list[str] | None,
        typer.Option("--source", help="Configured source to refresh."),
    ] = None,
    data_dir: DataDirectory = None,
    config_dir: ConfigDirectory = None,
) -> None:
    """Refresh enabled automated sources; unavailable connectors are skipped."""

    store, resolved_config = _runtime(data_dir, config_dir)
    config = load_config(resolved_config)
    sources = source or [
        name
        for name, item in config.sources.sources.items()
        if item.enabled and item.mode != "manual_only"
    ]
    try:
        result = refresh_store(store, config, sources)
    except RefreshExecutionError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from None
    typer.echo(
        f"Refresh complete: {result.offers_saved} saved; "
        f"{len(result.skipped_sources)} skipped"
    )


@app.command()
def rescore(
    data_dir: DataDirectory = None,
    config_dir: ConfigDirectory = None,
) -> None:
    """Recalculate all locally stored offer scores."""

    store, resolved_config = _runtime(data_dir, config_dir)
    result = rescore_store(store, load_config(resolved_config))
    typer.echo(
        f"Rescored {result.offers_scored} offers ({result.score_version or 'empty'})"
    )


@app.command("import")
def import_file(
    file: ImportFile,
    preview: Annotated[
        bool,
        typer.Option("--preview", help="Validate and score without writing offers."),
    ] = False,
    data_dir: DataDirectory = None,
    config_dir: ConfigDirectory = None,
) -> None:
    """Import a bounded local JSON file, including manual-only sources."""

    store, resolved_config = _runtime(data_dir, config_dir)
    try:
        offers = parse_offer_import(file.read_bytes())
    except (OSError, OfferImportError) as error:
        if isinstance(error, OfferImportError):
            for issue in error.issues:
                typer.echo(f"{issue.path}: {issue.message}", err=True)
        else:
            typer.echo("Import file could not be read", err=True)
        raise typer.Exit(1) from None
    result = import_offers(
        offers,
        config=load_config(resolved_config),
        store=store,
        preview=preview,
    )
    if preview:
        typer.echo(
            f"Preview: {result.offers_seen} valid; "
            f"{result.offers_saved} would be saved"
        )
    else:
        typer.echo(
            f"Import complete: {result.offers_saved} saved from "
            f"{result.offers_seen} offers"
        )


@app.command()
def doctor(
    data_dir: DataDirectory = None,
    config_dir: ConfigDirectory = None,
) -> None:
    """Check runtime, local writes, configuration, schema, and source readiness."""

    resolved_data, resolved_config = _paths(data_dir, config_dir)
    database_path = resolved_data / "job-radar.db"
    failures = []
    version_ok = (3, 12) <= sys.version_info[:2] < (3, 13)
    typer.echo(f"Python: {'ok' if version_ok else 'requires 3.12'}")
    if not version_ok:
        failures.append("python")

    data_error = _private_directory_error(resolved_data)
    writable = data_error is None and os.access(resolved_data, os.W_OK)
    typer.echo(f"Local writes: {'available' if writable else 'unavailable'}")
    if not writable:
        failures.append("writes")
        typer.echo(
            f"Unsafe local path: {resolved_data}. {data_error or 'not writable'}. "
            "Use a dedicated directory; run chmod 700 on the directory and "
            "chmod 600 on existing Job Radar files."
        )

    schema_status = _inspect_database(database_path)
    typer.echo(f"Schema: {schema_status}")
    if schema_status != "ok":
        failures.append("schema")

    try:
        config = load_config(resolved_config)
        typer.echo("Configuration: valid")
    except ConfigError as error:
        typer.echo(f"Configuration: invalid ({error})")
        typer.echo(
            "Fix the configuration path: directories require chmod 700 and "
            "YAML/pointer files require chmod 600; symbolic links are refused."
        )
        raise typer.Exit(1) from error

    for name, source_config in sorted(config.sources.sources.items()):
        if source_config.mode == "manual_only":
            typer.echo(f"Source {name}: manual_only")
        elif not remote_connector_available(name, source_config.mode):
            typer.echo(f"Source {name}: unavailable in this version")
        elif source_config.api_key_env and not os.environ.get(
            source_config.api_key_env
        ):
            typer.echo(f"Source {name}: credential missing, refresh will be skipped")
        else:
            typer.echo(f"Source {name}: ready")

    if failures:
        raise typer.Exit(1)


def _inspect_database(path: Path) -> str:
    if not path.exists() and not path.is_symlink():
        return "missing"
    path_error = _private_file_error(path)
    if path_error is not None:
        return f"unsafe ({path_error})"
    try:
        connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        try:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        finally:
            connection.close()
    except sqlite3.DatabaseError:
        return "corrupt"
    if (
        version != CURRENT_SCHEMA_VERSION
        or integrity != "ok"
        or not PUBLIC_TABLE_NAMES.issubset(tables)
    ):
        return "incomplete"
    return "ok"


def _private_directory_error(path: Path) -> str | None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return "directory is missing"
    if stat.S_ISLNK(metadata.st_mode):
        return "symbolic links are refused"
    if not stat.S_ISDIR(metadata.st_mode):
        return "path is not a directory"
    mode = stat.S_IMODE(metadata.st_mode)
    if mode != 0o700:
        return f"permissions must be exactly 0700, got {mode:04o}"
    return None


def _private_file_error(path: Path) -> str | None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return "file is missing"
    if stat.S_ISLNK(metadata.st_mode):
        return "symbolic links are refused"
    if not stat.S_ISREG(metadata.st_mode):
        return "path is not a regular file"
    mode = stat.S_IMODE(metadata.st_mode)
    if mode != 0o600:
        return f"permissions must be exactly 0600, got {mode:04o}"
    return None


@app.command()
def serve(
    host: Annotated[str, typer.Option(help="Local bind address.")] = "127.0.0.1",
    port: Annotated[
        int,
        typer.Option(min=1, max=65535, help="Local port."),
    ] = 8000,
    data_dir: DataDirectory = None,
    config_dir: ConfigDirectory = None,
) -> None:
    """Start the API on a loopback interface only."""

    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host.casefold() == "localhost"
    if not loopback:
        typer.echo("Serve host must be a loopback interface.", err=True)
        raise typer.Exit(2)
    try:
        import uvicorn
    except ImportError as error:
        typer.echo("Serving requires the optional 'uvicorn' package.", err=True)
        raise typer.Exit(1) from error
    resolved_data, resolved_config = _paths(data_dir, config_dir)
    try:
        application = create_app(ApiSettings(resolved_data, resolved_config))
    except PrivatePathError as error:
        _fail_private_path(resolved_data, error)
    uvicorn.run(application, host=host, port=port, log_config=None)
