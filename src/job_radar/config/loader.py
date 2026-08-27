"""Load and initialize local Job Radar configuration without secret values."""

from __future__ import annotations

import os
import re
import secrets
import stat
from contextlib import suppress
from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError

from job_radar.config.defaults import EXAMPLE_FILENAMES, example_path
from job_radar.config.models import (
    AppConfig,
    ProfileConfig,
    ScoringConfig,
    SearchConfig,
    SourcesConfig,
    TaxonomyConfig,
)
from job_radar.local_security import PrivatePathError, ensure_private_directory


class ConfigError(ValueError):
    """A configuration error annotated with its local YAML path."""


ACTIVE_GENERATION_POINTER = ".current"
GENERATIONS_DIRECTORY = ".generations"
GENERATION_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")
PRIVATE_DIRECTORY_MODE = 0o700
PRIVATE_FILE_MODE = 0o600
LEGACY_TITLE_MISSING_CONDITION = "title_missing"

_CONFIG_MODELS: dict[str, type[BaseModel]] = {
    "profile.yml": ProfileConfig,
    "search.yml": SearchConfig,
    "scoring.yml": ScoringConfig,
    "sources.yml": SourcesConfig,
    "taxonomy.yml": TaxonomyConfig,
}


def initialize_config(config_dir: Path) -> list[Path]:
    """Create missing local configuration files from public templates.

    Existing files are deliberately preserved so initialization is safe to rerun.
    """
    try:
        ensure_private_directory(config_dir)
    except PrivatePathError as error:
        raise ConfigError(f"configuration directory permissions: {error}") from error
    _validate_private_directory(config_dir, "active configuration directory")
    pointer = config_dir / ACTIVE_GENERATION_POINTER
    try:
        pointer.lstat()
    except FileNotFoundError:
        pass
    else:
        load_config(config_dir)
        return []
    created: list[Path] = []
    for filename in EXAMPLE_FILENAMES:
        destination = config_dir / filename
        try:
            destination.lstat()
        except FileNotFoundError:
            pass
        else:
            _validate_private_file(destination)
            continue
        try:
            template = example_path(filename).read_text(encoding="utf-8")
        except OSError as error:
            raise ConfigError(f"{filename}: cannot read template") from error
        _write_template_atomically(destination, template)
        created.append(destination)
    return created


def load_config(config_dir: Path) -> AppConfig:
    """Validate and assemble every local YAML configuration file."""
    _validate_private_directory(config_dir, "active configuration directory")
    active_dir = _active_config_dir(config_dir)
    loaded = {
        filename.removesuffix(".yml"): _load_file(
            active_dir / filename, _CONFIG_MODELS[filename]
        )
        for filename in EXAMPLE_FILENAMES
    }
    return AppConfig.model_validate(loaded)


def _active_config_dir(config_dir: Path) -> Path:
    pointer = config_dir / ACTIVE_GENERATION_POINTER
    try:
        pointer_stat = pointer.lstat()
    except FileNotFoundError:
        return config_dir
    if stat.S_ISLNK(pointer_stat.st_mode) or not stat.S_ISREG(pointer_stat.st_mode):
        raise ConfigError("active generation pointer: expected a regular file")
    if stat.S_IMODE(pointer_stat.st_mode) != PRIVATE_FILE_MODE:
        raise ConfigError("active generation pointer: permissions must be 0600")
    try:
        generation_id = _read_private_file(pointer).strip()
    except ConfigError as error:
        raise ConfigError("active generation pointer: cannot be read") from error
    if GENERATION_ID_PATTERN.fullmatch(generation_id) is None:
        raise ConfigError("active generation pointer: invalid generation id")

    generations = config_dir / GENERATIONS_DIRECTORY
    generation = generations / generation_id
    try:
        generations_stat = generations.lstat()
        generation_stat = generation.lstat()
    except FileNotFoundError as error:
        raise ConfigError("active generation pointer: generation is missing") from error
    if (
        stat.S_ISLNK(generations_stat.st_mode)
        or not stat.S_ISDIR(generations_stat.st_mode)
        or stat.S_ISLNK(generation_stat.st_mode)
        or not stat.S_ISDIR(generation_stat.st_mode)
    ):
        raise ConfigError("active generation pointer: generation is invalid")
    _validate_private_directory(generations, "configuration generations directory")
    _validate_private_directory(generation, "active configuration directory")
    return generation


def _load_file[ConfigModel: BaseModel](
    path: Path, model: type[ConfigModel]
) -> ConfigModel:
    filename = path.name
    stem = path.stem
    try:
        path_stat = path.lstat()
    except FileNotFoundError:
        raise ConfigError(f"{filename}: required configuration file is missing")
    _validate_private_file(path, path_stat)

    try:
        data = yaml.safe_load(_read_private_file(path))
    except (OSError, yaml.YAMLError) as error:
        raise ConfigError(f"{filename}: invalid YAML") from error

    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigError(f"{filename}: expected a mapping")

    if model is ScoringConfig:
        data = _migrate_legacy_scoring_config(data)

    try:
        return model.model_validate(data)
    except ValidationError as error:
        raise ConfigError(_format_validation_errors(stem, error)) from error


def _validate_private_directory(path: Path, label: str) -> None:
    try:
        path_stat = path.lstat()
    except FileNotFoundError as error:
        raise ConfigError(f"{label}: required directory is missing") from error
    if stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISDIR(path_stat.st_mode):
        raise ConfigError(f"{label}: expected a directory")
    if stat.S_IMODE(path_stat.st_mode) != PRIVATE_DIRECTORY_MODE:
        raise ConfigError(f"{label}: permissions must be 0700")


def _validate_private_file(path: Path, path_stat: os.stat_result | None = None) -> None:
    try:
        path_stat = path_stat or path.lstat()
    except FileNotFoundError as error:
        raise ConfigError(f"{path.name}: required configuration file is missing") from error
    if stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISREG(path_stat.st_mode):
        raise ConfigError(f"{path.name}: expected a regular file")
    if stat.S_IMODE(path_stat.st_mode) != PRIVATE_FILE_MODE:
        raise ConfigError(f"{path.name}: permissions must be 0600")


def _read_private_file(path: Path) -> str:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ConfigError(f"{path.name}: cannot be read") from error
    try:
        _validate_private_file(path, os.fstat(descriptor))
        with os.fdopen(descriptor, "r", encoding="utf-8", closefd=False) as stream:
            return stream.read()
    finally:
        os.close(descriptor)


def _write_template_atomically(destination: Path, template: str) -> None:
    temporary = destination.parent / f".{destination.name}.{secrets.token_hex(12)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(temporary, flags, PRIVATE_FILE_MODE)
        try:
            os.fchmod(descriptor, PRIVATE_FILE_MODE)
            with os.fdopen(descriptor, "w", encoding="utf-8", closefd=False) as stream:
                stream.write(template)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            os.close(descriptor)
        os.link(temporary, destination, follow_symlinks=False)
        _fsync_directory(destination.parent)
    except FileExistsError as error:
        raise ConfigError(f"{destination.name}: file already exists") from error
    except OSError as error:
        raise ConfigError(f"{destination.name}: cannot write template") from error
    finally:
        with suppress(OSError):
            temporary.unlink()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _migrate_legacy_scoring_config(data: dict[object, object]) -> dict[object, object]:
    blockers = data.get("blockers")
    if not isinstance(blockers, list):
        return data
    migrated = [
        blocker
        for blocker in blockers
        if not (
            isinstance(blocker, dict)
            and blocker.get("condition") == LEGACY_TITLE_MISSING_CONDITION
        )
    ]
    if len(migrated) == len(blockers):
        return data
    return {**data, "blockers": migrated}


def _format_validation_errors(stem: str, error: ValidationError) -> str:
    """Render stable field paths while intentionally omitting rejected values."""
    messages = []
    for detail in error.errors():
        location = ".".join(str(part) for part in detail["loc"])
        path = f"{stem}.{location}" if location else stem
        messages.append(f"{path}: {detail['msg']}")
    return "\n".join(messages)
