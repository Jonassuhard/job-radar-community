"""FastAPI application factory with local-only runtime state."""

from __future__ import annotations

import os
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from job_radar.api.routes import router
from job_radar.config.defaults import default_config_dir
from job_radar.db.store import RadarStore


@dataclass(frozen=True, slots=True)
class ApiSettings:
    data_dir: Path
    config_dir: Path
    database_name: str = "job-radar.db"
    allow_testclient: bool = False

    @property
    def database_path(self) -> Path:
        return self.data_dir / self.database_name


def default_settings() -> ApiSettings:
    data_dir = Path(
        os.environ.get(
            "JOB_RADAR_DATA_DIR", Path.home() / ".local" / "share" / "job-radar"
        )
    ).expanduser()
    return ApiSettings(data_dir=data_dir, config_dir=default_config_dir())


def _write_session_token(path: Path, token: str) -> None:
    temporary = path.parent / f".{path.name}.{secrets.token_hex(12)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", closefd=False) as stream:
            stream.write(token)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        path.chmod(0o600, follow_symlinks=False)
    finally:
        os.close(descriptor)
        with suppress(OSError):
            temporary.unlink()


@asynccontextmanager
async def _local_session(application: FastAPI) -> AsyncIterator[None]:
    token_path = application.state.session_token_path
    token = application.state.session_token
    _write_session_token(token_path, token)
    try:
        yield
    finally:
        try:
            if (
                token_path.is_file()
                and not token_path.is_symlink()
                and token_path.read_text(encoding="utf-8") == token
            ):
                token_path.unlink()
        except OSError:
            pass


def create_app(settings: ApiSettings | None = None) -> FastAPI:
    """Build one local API instance and issue a fresh in-memory write token."""

    resolved = settings or default_settings()
    application = FastAPI(
        title="Job Radar Community API",
        version="0.1.0-beta.1",
        description="Local API for offers, market insights, sources, and configuration.",
        lifespan=_local_session,
    )
    application.state.settings = resolved
    application.state.store = RadarStore(resolved.database_path)
    application.state.session_token = secrets.token_urlsafe(32)
    application.state.session_token_path = resolved.data_dir / "session-token"
    application.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", "X-Job-Radar-Token"],
    )
    application.include_router(router)
    return application
