from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from job_radar.api import routes
from job_radar.config.loader import ConfigError, initialize_config, load_config
from job_radar.config.models import AppConfig


def _updated_config(config_dir: Path) -> AppConfig:
    payload = load_config(config_dir).model_dump()
    payload["profile"]["roles"] = ["Generation role"]
    payload["search"]["locations"] = ["Generation city"]
    payload["scoring"]["thresholds"]["minimum_confidence"] = 77
    payload["sources"]["sources"]["local_demo"]["enabled"] = False
    payload["taxonomy"]["required"] = ["generation_skill"]
    return AppConfig.model_validate(payload)


@pytest.mark.parametrize(
    ("phase", "expected_generation"),
    [("before", "old"), ("after", "new")],
)
def test_process_crash_at_generation_switch_never_exposes_mixed_config(
    tmp_path, phase, expected_generation
):
    config_dir = tmp_path / "config"
    initialize_config(config_dir)
    old_config = load_config(config_dir)
    new_config = _updated_config(config_dir)
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(new_config.model_dump_json(), encoding="utf-8")
    project_root = Path(__file__).resolve().parents[2]
    script = """
import json
import os
import sys
from pathlib import Path
from job_radar.api import routes
from job_radar.config.models import AppConfig

config_dir = Path(sys.argv[1])
payload = AppConfig.model_validate(json.loads(Path(sys.argv[2]).read_text()))
phase = sys.argv[3]
real_replace = os.replace

def crash_at_switch(source, destination, *args, **kwargs):
    if Path(destination).name == '.current':
        if phase == 'before':
            os._exit(91)
        real_replace(source, destination, *args, **kwargs)
        os._exit(92)
    return real_replace(source, destination, *args, **kwargs)

routes.os.replace = crash_at_switch
routes._write_config(config_dir, payload)
"""
    environment = os.environ | {"PYTHONPATH": str(project_root / "src")}

    result = subprocess.run(
        [sys.executable, "-c", script, str(config_dir), str(payload_path), phase],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode in {91, 92}, result.stderr
    loaded = load_config(config_dir)
    expected = old_config if expected_generation == "old" else new_config
    assert loaded.model_dump() == expected.model_dump()


def test_successful_write_publishes_one_complete_immutable_generation(tmp_path):
    config_dir = tmp_path / "config"
    initialize_config(config_dir)
    updated = _updated_config(config_dir)

    routes._write_config(config_dir, updated)

    pointer = config_dir / ".current"
    generation_id = pointer.read_text(encoding="utf-8").strip()
    generation = config_dir / ".generations" / generation_id
    assert stat.S_IMODE(pointer.stat().st_mode) == 0o600
    assert stat.S_IMODE((config_dir / ".generations").stat().st_mode) == 0o700
    assert stat.S_IMODE(generation.stat().st_mode) == 0o700
    assert sorted(path.name for path in generation.iterdir()) == [
        "profile.yml",
        "scoring.yml",
        "search.yml",
        "sources.yml",
        "taxonomy.yml",
    ]
    assert all(
        stat.S_IMODE(path.stat().st_mode) == 0o600 for path in generation.iterdir()
    )
    assert load_config(config_dir).model_dump() == updated.model_dump()


def test_write_config_refuses_permissive_existing_root_without_chmod(tmp_path):
    source_dir = tmp_path / "source-config"
    initialize_config(source_dir)
    updated = _updated_config(source_dir)
    config_dir = tmp_path / "unsafe-config"
    config_dir.mkdir(mode=0o755)

    with pytest.raises(routes.ConfigWriteError, match="Configuration update failed"):
        routes._write_config(config_dir, updated)

    assert stat.S_IMODE(config_dir.stat().st_mode) == 0o755
    assert list(config_dir.iterdir()) == []


def test_write_config_refuses_permissive_generations_directory_without_chmod(
    tmp_path,
):
    config_dir = tmp_path / "config"
    initialize_config(config_dir)
    updated = _updated_config(config_dir)
    generations = config_dir / ".generations"
    generations.mkdir(mode=0o755)

    with pytest.raises(routes.ConfigWriteError, match="Configuration update failed"):
        routes._write_config(config_dir, updated)

    assert stat.S_IMODE(generations.stat().st_mode) == 0o755
    assert list(generations.iterdir()) == []


@pytest.mark.parametrize("pointer_value", ["../outside", "bad/id", "", "not-hex"])
def test_load_config_rejects_invalid_generation_pointer(tmp_path, pointer_value):
    config_dir = tmp_path / "config"
    initialize_config(config_dir)
    (config_dir / ".current").write_text(pointer_value, encoding="utf-8")

    with pytest.raises(ConfigError, match="active generation pointer"):
        load_config(config_dir)


def test_load_config_rejects_symlinked_pointer(tmp_path):
    config_dir = tmp_path / "config"
    initialize_config(config_dir)
    external = tmp_path / "external-pointer"
    external.write_text("a" * 32, encoding="utf-8")
    (config_dir / ".current").symlink_to(external)

    with pytest.raises(ConfigError, match="active generation pointer"):
        load_config(config_dir)


def test_flat_symlink_is_never_read_or_written_during_migration(tmp_path):
    config_dir = tmp_path / "config"
    initialize_config(config_dir)
    updated = _updated_config(config_dir)
    external = tmp_path / "external-profile.yml"
    external.write_text("safe", encoding="utf-8")
    profile = config_dir / "profile.yml"
    profile.unlink()
    profile.symlink_to(external)

    with pytest.raises(ConfigError, match="profile.yml"):
        load_config(config_dir)

    routes._write_config(config_dir, updated)
    assert external.read_text(encoding="utf-8") == "safe"
    assert load_config(config_dir).model_dump() == updated.model_dump()
