"""Locations of versioned, public-safe configuration templates."""

from __future__ import annotations

import os
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path

EXAMPLE_FILENAMES = (
    "profile.yml",
    "search.yml",
    "scoring.yml",
    "sources.yml",
    "taxonomy.yml",
)

CONFIG_DIRECTORY_ENV = "JOB_RADAR_CONFIG_DIR"


def example_path(filename: str) -> Traversable:
    """Return a template embedded in the installed package."""
    if filename not in EXAMPLE_FILENAMES:
        raise ValueError(f"unknown configuration template: {filename}")
    return files("job_radar.data.config").joinpath(filename)


def default_config_dir() -> Path:
    """Return the local configuration directory, honoring its safe override."""
    configured_path = os.environ.get(CONFIG_DIRECTORY_ENV)
    if configured_path:
        return Path(configured_path).expanduser()
    return Path.home() / ".config" / "job-radar"
