from __future__ import annotations

import os
import stat
from importlib.resources import files
from pathlib import Path

import pytest
import yaml

from job_radar.config.defaults import EXAMPLE_FILENAMES, default_config_dir
from job_radar.config.loader import ConfigError, initialize_config, load_config


def test_examples_form_a_valid_config(tmp_path):
    initialize_config(tmp_path)

    config = load_config(tmp_path)

    assert sum(axis.weight for axis in config.scoring.axes) == 100
    assert config.sources.sources["indeed"].mode == "manual_only"


def test_initialize_config_creates_private_permissions(tmp_path):
    config_dir = tmp_path / "config"
    previous_umask = os.umask(0)
    try:
        initialize_config(config_dir)
    finally:
        os.umask(previous_umask)

    assert stat.S_IMODE(config_dir.stat().st_mode) == 0o700
    for filename in EXAMPLE_FILENAMES:
        assert stat.S_IMODE((config_dir / filename).stat().st_mode) == 0o600


def test_initialize_config_refuses_permissive_existing_directory_without_chmod(
    tmp_path,
):
    config_dir = tmp_path / "config"
    config_dir.mkdir(mode=0o755)

    with pytest.raises(ConfigError, match="permissions"):
        initialize_config(config_dir)

    assert stat.S_IMODE(config_dir.stat().st_mode) == 0o755
    assert list(config_dir.iterdir()) == []


def test_initialize_config_refuses_symlinked_directory(tmp_path):
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    config_dir = tmp_path / "config"
    config_dir.symlink_to(target, target_is_directory=True)

    with pytest.raises(ConfigError, match="symbolic link"):
        initialize_config(config_dir)

    assert list(target.iterdir()) == []


def test_initialize_config_leaves_no_empty_template_when_template_read_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class UnreadableTemplate:
        def read_text(self, *, encoding: str) -> str:
            del encoding
            raise OSError("template unavailable")

    monkeypatch.setattr(
        "job_radar.config.loader.example_path", lambda filename: UnreadableTemplate()
    )

    with pytest.raises(ConfigError, match="profile.yml: cannot read template"):
        initialize_config(tmp_path / "config")

    assert not (tmp_path / "config" / "profile.yml").exists()


def test_initialize_config_cleans_up_template_when_atomic_publish_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_sync(descriptor: int) -> None:
        del descriptor
        raise OSError("storage unavailable")

    monkeypatch.setattr("job_radar.config.loader.os.fsync", fail_sync)

    with pytest.raises(ConfigError, match="profile.yml: cannot write template"):
        initialize_config(tmp_path / "config")

    config_dir = tmp_path / "config"
    assert not (config_dir / "profile.yml").exists()
    assert not list(config_dir.glob(".profile.yml.*.tmp"))


def test_load_config_refuses_permissive_flat_config_directory_without_chmod(
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "config"
    initialize_config(config_dir)
    config_dir.chmod(0o755)

    with pytest.raises(ConfigError, match="active configuration directory.*0700"):
        load_config(config_dir)

    assert stat.S_IMODE(config_dir.stat().st_mode) == 0o755


def test_load_config_refuses_permissive_flat_yaml_without_chmod(tmp_path: Path) -> None:
    initialize_config(tmp_path)
    search = tmp_path / "search.yml"
    search.chmod(0o644)

    with pytest.raises(ConfigError, match="search.yml: permissions must be 0600"):
        load_config(tmp_path)

    assert stat.S_IMODE(search.stat().st_mode) == 0o644


def test_load_config_refuses_symlinked_flat_yaml(tmp_path: Path) -> None:
    initialize_config(tmp_path)
    external = tmp_path / "external-search.yml"
    external.write_text("locations: []\n", encoding="utf-8")
    search = tmp_path / "search.yml"
    search.unlink()
    search.symlink_to(external)

    with pytest.raises(ConfigError, match="search.yml: expected a regular file"):
        load_config(tmp_path)


def _activate_generation(config_dir: Path, generation_id: str = "a" * 32) -> Path:
    generation = config_dir / ".generations" / generation_id
    generation.parent.mkdir(mode=0o700)
    generation.mkdir(mode=0o700)
    for filename in EXAMPLE_FILENAMES:
        destination = generation / filename
        destination.write_text(
            files("job_radar.data.config").joinpath(filename).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        destination.chmod(0o600)
    pointer = config_dir / ".current"
    pointer.write_text(f"{generation_id}\n", encoding="utf-8")
    pointer.chmod(0o600)
    return generation


def test_initialize_config_is_idempotent_with_a_valid_active_generation(
    tmp_path: Path,
) -> None:
    initialize_config(tmp_path)
    _activate_generation(tmp_path)

    assert initialize_config(tmp_path) == []


def test_initialize_config_rejects_invalid_active_generation_id(tmp_path: Path) -> None:
    initialize_config(tmp_path)
    pointer = tmp_path / ".current"
    pointer.write_text("not-a-generation\n", encoding="utf-8")
    pointer.chmod(0o600)

    with pytest.raises(ConfigError, match="active generation pointer: invalid generation id"):
        initialize_config(tmp_path)


def test_initialize_config_rejects_symlinked_active_generation_pointer(
    tmp_path: Path,
) -> None:
    initialize_config(tmp_path)
    external = tmp_path / "external-pointer"
    external.write_text(f"{'a' * 32}\n", encoding="utf-8")
    external.chmod(0o600)
    (tmp_path / ".current").symlink_to(external)

    with pytest.raises(ConfigError, match="active generation pointer: expected a regular file"):
        initialize_config(tmp_path)


def test_initialize_config_rejects_permissive_active_generation_pointer(
    tmp_path: Path,
) -> None:
    initialize_config(tmp_path)
    pointer = tmp_path / ".current"
    pointer.write_text(f"{'a' * 32}\n", encoding="utf-8")
    pointer.chmod(0o644)

    with pytest.raises(ConfigError, match="active generation pointer: permissions must be 0600"):
        initialize_config(tmp_path)


def test_initialize_config_rejects_missing_active_generation(tmp_path: Path) -> None:
    initialize_config(tmp_path)
    pointer = tmp_path / ".current"
    pointer.write_text(f"{'a' * 32}\n", encoding="utf-8")
    pointer.chmod(0o600)

    with pytest.raises(ConfigError, match="active generation pointer: generation is missing"):
        initialize_config(tmp_path)


def test_initialize_config_rejects_incomplete_active_generation(tmp_path: Path) -> None:
    initialize_config(tmp_path)
    generation = _activate_generation(tmp_path)
    (generation / "sources.yml").unlink()

    with pytest.raises(
        ConfigError, match="sources.yml: required configuration file is missing"
    ):
        initialize_config(tmp_path)


def test_load_config_refuses_permissive_active_generation_without_chmod(
    tmp_path: Path,
) -> None:
    initialize_config(tmp_path)
    generation = _activate_generation(tmp_path)
    generation.chmod(0o755)

    with pytest.raises(ConfigError, match="active configuration directory.*0700"):
        load_config(tmp_path)

    assert stat.S_IMODE(generation.stat().st_mode) == 0o755


def test_load_config_refuses_permissive_active_generation_yaml_without_chmod(
    tmp_path: Path,
) -> None:
    initialize_config(tmp_path)
    generation = _activate_generation(tmp_path)
    scoring = generation / "scoring.yml"
    scoring.chmod(0o644)

    with pytest.raises(ConfigError, match="scoring.yml: permissions must be 0600"):
        load_config(tmp_path)

    assert stat.S_IMODE(scoring.stat().st_mode) == 0o644


def test_packaged_templates_stay_synchronized_with_repository_examples():
    packaged = files("job_radar.data.config")
    repository = Path(__file__).resolve().parents[2] / "config"
    for filename in EXAMPLE_FILENAMES:
        assert packaged.joinpath(filename).read_text(
            encoding="utf-8"
        ) == repository.joinpath(filename.replace(".yml", ".example.yml")).read_text(
            encoding="utf-8"
        )
    assert "title_missing" not in packaged.joinpath("scoring.yml").read_text(
        encoding="utf-8"
    )


def test_unknown_keys_are_rejected(tmp_path):
    initialize_config(tmp_path)
    (tmp_path / "search.yml").write_text("locations: []\nsurprise: true\n")

    with pytest.raises(ConfigError, match="search.surprise"):
        load_config(tmp_path)


def test_scoring_weights_must_total_one_hundred(tmp_path):
    initialize_config(tmp_path)
    (tmp_path / "scoring.yml").write_text(
        "axes:\n  - name: role\n    weight: 99\ndecisions: []\n"
    )

    with pytest.raises(ConfigError, match="scoring.axes"):
        load_config(tmp_path)


def test_decision_thresholds_must_increase(tmp_path):
    initialize_config(tmp_path)
    (tmp_path / "scoring.yml").write_text(
        "axes:\n  - name: role\n    weight: 100\n"
        "decisions:\n  - name: reject\n    min_score: 0\n"
        "  - name: monitor\n    min_score: 60\n"
        "  - name: review\n    min_score: 50\n"
        "  - name: prioritize\n    min_score: 85\n"
    )

    with pytest.raises(ConfigError, match="scoring.decisions"):
        load_config(tmp_path)


def test_negative_scoring_thresholds_are_rejected(tmp_path):
    initialize_config(tmp_path)
    (tmp_path / "scoring.yml").write_text(
        "axes:\n  - name: role\n    weight: 100\n"
        "thresholds:\n  minimum_confidence: -1\n"
    )

    with pytest.raises(ConfigError, match="scoring.thresholds.minimum_confidence"):
        load_config(tmp_path)


def test_scoring_caps_must_be_points(tmp_path):
    initialize_config(tmp_path)
    (tmp_path / "scoring.yml").write_text(
        "axes:\n  - name: role\n    weight: 100\ncaps:\n  bonus: 101\n"
    )

    with pytest.raises(ConfigError, match="scoring.caps.bonus"):
        load_config(tmp_path)


def test_scalar_boolean_is_not_coerced_to_salary(tmp_path):
    initialize_config(tmp_path)
    (tmp_path / "search.yml").write_text("salary_minimum: true\n")

    with pytest.raises(ConfigError, match="search.salary_minimum"):
        load_config(tmp_path)


def test_source_secrets_must_be_environment_variable_names(tmp_path):
    initialize_config(tmp_path)
    (tmp_path / "sources.yml").write_text(
        "sources:\n  sample:\n    mode: api\n    api_key_env: not-a-secret-value\n"
    )

    with pytest.raises(ConfigError, match="sources.sources.sample.api_key_env"):
        load_config(tmp_path)


def test_config_directory_can_be_overridden_by_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("JOB_RADAR_CONFIG_DIR", str(tmp_path))

    assert default_config_dir() == tmp_path


def _mutate_scoring(tmp_path: Path, mutate) -> None:
    initialize_config(tmp_path)
    path = tmp_path / "scoring.yml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


@pytest.mark.parametrize("axis", ["role", "skills_typo", "remote_fit"])
def test_unsupported_scoring_axes_are_rejected(tmp_path: Path, axis: str) -> None:
    _mutate_scoring(
        tmp_path,
        lambda payload: payload.update({"axes": [{"name": axis, "weight": 100}]}),
    )

    with pytest.raises(ConfigError, match="scoring.axes.0.name"):
        load_config(tmp_path)


@pytest.mark.parametrize(
    ("section", "name"),
    [
        ("thresholds", "unknown_threshold"),
        ("caps", "unknown_cap"),
    ],
)
def test_unknown_thresholds_and_caps_are_rejected(
    tmp_path: Path, section: str, name: str
) -> None:
    _mutate_scoring(tmp_path, lambda payload: payload[section].update({name: 10}))

    with pytest.raises(ConfigError, match=f"scoring.{section}"):
        load_config(tmp_path)


@pytest.mark.parametrize(
    ("section", "rule"),
    [
        ("bonuses", {"name": "network_effect", "points": 5}),
        ("penalties", {"name": "vague_copy", "points": 5}),
        ("blockers", {"name": "custom", "condition": "magic_condition"}),
    ],
)
def test_unimplemented_rules_and_conditions_are_rejected(
    tmp_path: Path, section: str, rule: dict[str, object]
) -> None:
    _mutate_scoring(tmp_path, lambda payload: payload.update({section: [rule]}))

    with pytest.raises(ConfigError, match=f"scoring.{section}"):
        load_config(tmp_path)


def test_legacy_title_missing_blocker_loads_without_reintroducing_condition(
    tmp_path: Path,
) -> None:
    _mutate_scoring(
        tmp_path,
        lambda payload: payload.update(
            {"blockers": [{"name": "missing_title", "condition": "title_missing"}]}
        ),
    )

    config = load_config(tmp_path)

    assert config.scoring.blockers == []
    assert "title_missing" in (tmp_path / "scoring.yml").read_text(encoding="utf-8")


def test_custom_source_keys_are_nfkc_casefolded_and_space_normalized(
    tmp_path: Path,
) -> None:
    initialize_config(tmp_path)
    sources_path = tmp_path / "sources.yml"
    payload = yaml.safe_load(sources_path.read_text(encoding="utf-8"))
    payload["sources"][" ＥＣＯＬＥ  ATS "] = {"mode": "ats"}
    sources_path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")

    config = load_config(tmp_path)

    assert "ecole ats" in config.sources.sources


def test_custom_source_keys_must_be_unique_after_normalization(tmp_path: Path) -> None:
    initialize_config(tmp_path)
    sources_path = tmp_path / "sources.yml"
    sources_path.write_text(
        yaml.safe_dump(
            {
                "sources": {
                    "ÉCOLE ATS": {"mode": "ats"},
                    "e\u0301cole   ats": {"mode": "api"},
                }
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="sources.sources"):
        load_config(tmp_path)


def test_decision_vocabulary_is_closed(tmp_path: Path) -> None:
    def mutate(payload):
        payload["decisions"][1]["name"] = "consider"

    _mutate_scoring(tmp_path, mutate)

    with pytest.raises(ConfigError, match="scoring.decisions.1.name"):
        load_config(tmp_path)


def test_all_four_public_decisions_are_required(tmp_path: Path) -> None:
    def mutate(payload):
        payload["decisions"].pop()

    _mutate_scoring(tmp_path, mutate)

    with pytest.raises(ConfigError, match="scoring.decisions"):
        load_config(tmp_path)


def test_decisions_cannot_be_omitted(tmp_path: Path) -> None:
    _mutate_scoring(tmp_path, lambda payload: payload.pop("decisions"))

    with pytest.raises(ConfigError, match="scoring.decisions"):
        load_config(tmp_path)


def test_examples_use_the_public_decision_vocabulary(tmp_path: Path) -> None:
    initialize_config(tmp_path)

    config = load_config(tmp_path)

    assert [decision.name for decision in config.scoring.decisions] == [
        "reject",
        "monitor",
        "review",
        "prioritize",
    ]
