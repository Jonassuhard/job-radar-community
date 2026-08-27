"""Release source archive contract tests."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

import pytest

from scripts.build_release import (
    ReleaseBuildError,
    build_candidate_archive,
    build_release,
)

RELEASE = "v0.1.0-beta.1"
VERIFICATION_PATH = Path("docs/verification/v0.1.0-beta.1.json")
VERIFIED_AT = "2026-08-27T22:12:00+02:00"
PUBLICATION_OBSERVED_AT = "2026-08-27T22:13:00+02:00"
OPENAPI_DOCUMENT = (
    '{"openapi":"3.1.0","paths":{"/health":{"get":{}}}}\n'
)
CAPTURE_CONTENT = b"fixture capture\n"
FIXTURE_ENVIRONMENT = {
    "platform": "test",
    "services": ["fixture"],
    "dataset": "fixture",
}
FIXTURE_VERSIONS = {
    "python": "3.12.1",
    "node": "25.8.2",
    "npm": "11.11.1",
    "uv": "0.11.3",
    "playwright": "1.62.1",
}
FIXTURE_LIMITATIONS = ["This candidate was not published when observed."]


def _fixture_capture() -> dict[str, object]:
    return {
        "file": "capture.webp",
        "sha256": hashlib.sha256(CAPTURE_CONTENT).hexdigest(),
        "bytes": len(CAPTURE_CONTENT),
        "dimensions": [1, 1],
        "ocr_pii_findings": 0,
        "non_example_domains": [],
    }


def _fixture_checks() -> dict[str, object]:
    return {
        "backend_tests": {"passed": 1, "failed": 0},
        "frontend_tests": {"passed": 2, "failed": 0},
        "e2e_tests": {"passed": 3, "failed": 0, "skipped": 0},
        "axe": {"routes_scanned": 1, "violations": 0},
        "responsive": {"routes_checked": 1, "widths": [390]},
        "frontend_build": {"status": "passed"},
        "openapi": {
            "status": "passed",
            "document_sha256": hashlib.sha256(OPENAPI_DOCUMENT.encode()).hexdigest(),
            "paths": 1,
            "operations": 1,
        },
        "ruff": {"findings": 0},
        "release_build": {"runs": 2, "deterministic": True},
        "audits": {
            "public_tree": {"findings": 0},
            "git_history": {"findings": 0},
            "release_archive": {"findings": 0},
            "python_distributions": {"artifacts": 2, "findings": 0},
            "npm": {"findings": 0},
            "python": {"findings": 0},
        },
    }


def _fixture_contract() -> dict[str, object]:
    return {
        "schema_version": 1,
        "release": RELEASE,
        "verification_schema_version": 2,
        "expected_environment": FIXTURE_ENVIRONMENT,
        "expected_versions": FIXTURE_VERSIONS,
        "expected_checks": _fixture_checks(),
        "expected_captures": [_fixture_capture()],
        "expected_limitations": FIXTURE_LIMITATIONS,
    }


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _commit(root: Path, message: str) -> str:
    _git(root, "add", "-A")
    _git(
        root,
        "-c",
        "user.name=Release Test",
        "-c",
        "user.email=release-test@example.com",
        "commit",
        "--quiet",
        "-m",
        message,
    )
    return _git(root, "rev-parse", "HEAD")


def _pending_verification() -> dict[str, object]:
    return {
        "schema_version": 2,
        "release": RELEASE,
        "status": "pending_commit_pin",
        "tested_product_commit": None,
        "test_harness_commit": None,
        "verified_at": None,
        "publication": {"status": "not_observed", "observed_at": None},
        "limitations": ["No result is verified while the tested commit is pending."],
    }


def _verified_verification(tested_commit: str) -> dict[str, object]:
    return {
        "schema_version": 2,
        "release": RELEASE,
        "status": "local_candidate_verified",
        "tested_product_commit": tested_commit,
        "test_harness_commit": tested_commit,
        "verified_at": VERIFIED_AT,
        "publication": {
            "status": "not_published",
            "observed_at": PUBLICATION_OBSERVED_AT,
        },
        "environment": FIXTURE_ENVIRONMENT,
        "versions": FIXTURE_VERSIONS,
        "checks": _fixture_checks(),
        "captures": [_fixture_capture()],
        "limitations": FIXTURE_LIMITATIONS,
    }


def _write_verification(root: Path, payload: dict[str, object]) -> None:
    (root / VERIFICATION_PATH).write_text(
        json.dumps(payload, sort_keys=True), encoding="utf-8"
    )


def _project(root: Path, manifest: str) -> None:
    (root / "README.md").write_text("public\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "[project]\nname = 'release-test'\nversion = '0.1.0b1'\n",
        encoding="utf-8",
    )
    (root / "PUBLIC_MANIFEST").write_text(
        manifest + "docs/\nscripts/\n", encoding="utf-8"
    )
    verification = root / "docs" / "verification"
    verification.mkdir(parents=True)
    _write_verification(root, _pending_verification())
    (verification / "v0.1.0-beta.1-contract.json").write_text(
        json.dumps(_fixture_contract(), sort_keys=True), encoding="utf-8"
    )
    media_record = {
        **_fixture_capture(),
        "metadata_findings": [],
        "pii_findings": [],
    }
    media_record.pop("ocr_pii_findings")
    (verification / "v0.1.0-beta.1-media.json").write_text(
        json.dumps(
            {
                "images": [media_record],
                "summary": {
                    "images": 1,
                    "metadata_findings": 0,
                    "non_example_domains": 0,
                    "pii_findings": 0,
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    assets = root / "docs" / "assets"
    assets.mkdir()
    (assets / "capture.webp").write_bytes(CAPTURE_CONTENT)
    (root / "docs" / "RELEASE_VERIFICATION.md").write_text(
        "# Release verification\n", encoding="utf-8"
    )
    scripts = root / "scripts"
    scripts.mkdir()
    (scripts / "export_openapi.py").write_text(
        f"import sys\nsys.stdout.write({OPENAPI_DOCUMENT!r})\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "--quiet"], cwd=root, check=True)
    tested_commit = _commit(root, "fixture")
    _write_verification(root, _verified_verification(tested_commit))
    _commit(root, "verification")


def _pending_project(root: Path, manifest: str) -> None:
    _project(root, manifest)
    _write_verification(root, _pending_verification())
    _commit(root, "return verification to pending")


@pytest.mark.parametrize("entry", ["missing.txt", "../README.md", "/tmp/README.md"])
def test_builder_rejects_missing_or_unsafe_manifest_entries(tmp_path: Path, entry: str) -> None:
    root = tmp_path / "project"
    root.mkdir()
    _project(root, f"PUBLIC_MANIFEST\nREADME.md\npyproject.toml\n{entry}\n")

    with pytest.raises(ReleaseBuildError):
        build_release(root, tmp_path / "out", tag="v0.1.0-beta.1")


def test_builder_rejects_tracked_symlink(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    _project(root, "PUBLIC_MANIFEST\nREADME.md\npyproject.toml\nlinked\n")
    target = root / "target.txt"
    target.write_text("public\n", encoding="utf-8")
    (root / "linked").symlink_to(target.name)
    _commit(root, "add symlink")

    with pytest.raises(ReleaseBuildError, match="symlink"):
        build_release(root, tmp_path / "out", tag="v0.1.0-beta.1")


def test_builder_is_deterministic_and_writes_portable_checksum(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    _project(root, "PUBLIC_MANIFEST\nREADME.md\npyproject.toml\n")

    first = build_release(root, tmp_path / "one", tag="v0.1.0-beta.1")
    os.utime(root / "README.md", (1_700_000_000, 1_700_000_000))
    second = build_release(root, tmp_path / "two", tag="v0.1.0-beta.1")

    assert hashlib.sha256(first.archive.read_bytes()).digest() == hashlib.sha256(
        second.archive.read_bytes()
    ).digest()
    assert first.checksum.read_text(encoding="utf-8").endswith(
        f"  {first.archive.name}\n"
    )
    assert first.attestation.read_bytes() == second.attestation.read_bytes()


def test_builder_writes_external_attestation_that_recalculates_release(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    _project(root, "PUBLIC_MANIFEST\nREADME.md\npyproject.toml\n")

    artifacts = build_release(root, tmp_path / "out", tag="v0.1.0-beta.1")
    payload = json.loads(artifacts.attestation.read_text(encoding="utf-8"))
    verification = root / "docs/verification/v0.1.0-beta.1.json"
    openapi = subprocess.run(
        [sys.executable, str(root / "scripts/export_openapi.py")],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout

    assert payload["schema_version"] == 2
    assert payload["release"] == RELEASE
    assert payload["status"] == "local_candidate_verified"
    assert payload["verified_at"] == VERIFIED_AT
    assert payload["publication"] == {
        "status": "not_published",
        "observed_at": PUBLICATION_OBSERVED_AT,
    }
    assert payload["release_commit"] == subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()
    assert payload["release_tree"] == subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert payload["builder_observations"]["archive"] == {
        "file": artifacts.archive.name,
        "sha256": hashlib.sha256(artifacts.archive.read_bytes()).hexdigest(),
        "bytes": artifacts.archive.stat().st_size,
        "files": 9,
    }
    assert payload["builder_observations"]["openapi"] == {
        "status": "passed",
        "document_sha256": hashlib.sha256(openapi).hexdigest(),
        "paths": 1,
        "operations": 1,
    }
    assert payload["builder_observations"]["attestation"] == {
        "status": "generated_by_build_release",
        "file": artifacts.attestation.name,
    }
    integrity = payload["builder_observations"]["verification_record_integrity"]
    assert integrity == {
        "file": "docs/verification/v0.1.0-beta.1.json",
        "sha256": hashlib.sha256(verification.read_bytes()).hexdigest(),
        "contract_file": "docs/verification/v0.1.0-beta.1-contract.json",
        "contract_sha256": hashlib.sha256(
            (root / "docs/verification/v0.1.0-beta.1-contract.json").read_bytes()
        ).hexdigest(),
        "contract_status": "matched",
    }
    assert "did not execute these tests or audits" in payload["declared_verification"][
        "provenance"
    ]
    assert payload["declared_verification"]["checks"] == _fixture_checks()
    assert payload["declared_verification"]["captures"] == [_fixture_capture()]
    assert "checks" not in payload
    with ZipFile(artifacts.archive) as archive:
        assert all(not name.endswith(".attestation.json") for name in archive.namelist())


@pytest.mark.parametrize("field", ["tested_product_commit", "test_harness_commit"])
def test_builder_requires_explicitly_pinned_verification_commits(
    tmp_path: Path, field: str
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    _project(root, "PUBLIC_MANIFEST\nREADME.md\npyproject.toml\n")
    verification_path = root / "docs/verification/v0.1.0-beta.1.json"
    verification = json.loads(verification_path.read_text(encoding="utf-8"))
    verification.pop(field)
    verification_path.write_text(json.dumps(verification), encoding="utf-8")
    _commit(root, f"remove {field}")

    with pytest.raises(ReleaseBuildError, match=field):
        build_release(root, tmp_path / "out", tag="v0.1.0-beta.1")


def test_builder_rejects_pending_verification(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    _pending_project(root, "PUBLIC_MANIFEST\nREADME.md\npyproject.toml\n")

    output = tmp_path / "out"
    with pytest.raises(ReleaseBuildError, match="status must be local_candidate_verified"):
        build_release(root, output, tag=RELEASE)

    assert not output.exists()


def test_candidate_archive_accepts_pending_without_emitting_attestation(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    _pending_project(root, "PUBLIC_MANIFEST\nREADME.md\npyproject.toml\n")

    artifacts = build_candidate_archive(root, tmp_path / "out", tag=RELEASE)

    assert artifacts.archive.is_file()
    assert artifacts.checksum.is_file()
    assert artifacts.staging.is_dir()
    assert not artifacts.archive.with_suffix(".attestation.json").exists()
    assert not hasattr(artifacts, "attestation")


def test_builder_rejects_wrong_verification_schema(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    _project(root, "PUBLIC_MANIFEST\nREADME.md\npyproject.toml\n")
    payload = json.loads((root / VERIFICATION_PATH).read_text(encoding="utf-8"))
    payload["schema_version"] = 1
    _write_verification(root, payload)
    _commit(root, "downgrade verification schema")

    with pytest.raises(ReleaseBuildError, match="schema_version 2"):
        build_release(root, tmp_path / "out", tag=RELEASE)


@pytest.mark.parametrize("observed_at", [None, "2026-08-27T22:13:00"])
def test_builder_requires_a_timezone_aware_publication_observation(
    tmp_path: Path, observed_at: str | None
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    _project(root, "PUBLIC_MANIFEST\nREADME.md\npyproject.toml\n")
    payload = json.loads((root / VERIFICATION_PATH).read_text(encoding="utf-8"))
    payload["publication"]["observed_at"] = observed_at
    _write_verification(root, payload)
    _commit(root, "invalidate publication observation")

    with pytest.raises(ReleaseBuildError, match="observed_at"):
        build_release(root, tmp_path / "out", tag=RELEASE)


def test_builder_rejects_invented_test_and_audit_claims(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    _project(root, "PUBLIC_MANIFEST\nREADME.md\npyproject.toml\n")
    payload = json.loads((root / VERIFICATION_PATH).read_text(encoding="utf-8"))
    payload["checks"]["backend_tests"]["passed"] = 999_999
    payload["checks"]["audits"]["invented"] = {"findings": 0}
    _write_verification(root, payload)
    _commit(root, "invent verification claims")

    with pytest.raises(ReleaseBuildError, match="checks.+immutable contract"):
        build_release(root, tmp_path / "out", tag=RELEASE)


def test_builder_rejects_future_verification_timestamp(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    _project(root, "PUBLIC_MANIFEST\nREADME.md\npyproject.toml\n")
    payload = json.loads((root / VERIFICATION_PATH).read_text(encoding="utf-8"))
    payload["verified_at"] = "2099-01-01T00:00:00+00:00"
    _write_verification(root, payload)
    _commit(root, "future verification")

    with pytest.raises(ReleaseBuildError, match="verified_at in the future"):
        build_release(root, tmp_path / "out", tag=RELEASE)


def test_builder_rejects_published_local_candidate(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    _project(root, "PUBLIC_MANIFEST\nREADME.md\npyproject.toml\n")
    payload = json.loads((root / VERIFICATION_PATH).read_text(encoding="utf-8"))
    payload["publication"]["status"] = "published"
    _write_verification(root, payload)
    _commit(root, "claim publication")

    with pytest.raises(ReleaseBuildError, match="must be not_published"):
        build_release(root, tmp_path / "out", tag=RELEASE)


def test_builder_rejects_unknown_verification_field(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    _project(root, "PUBLIC_MANIFEST\nREADME.md\npyproject.toml\n")
    payload = json.loads((root / VERIFICATION_PATH).read_text(encoding="utf-8"))
    payload["reviewer_override"] = True
    _write_verification(root, payload)
    _commit(root, "add unknown verification field")

    with pytest.raises(ReleaseBuildError, match="missing or unknown fields"):
        build_release(root, tmp_path / "out", tag=RELEASE)


@pytest.mark.parametrize("staged", [False, True], ids=["worktree", "index"])
def test_builder_refuses_dirty_tracked_content(tmp_path: Path, staged: bool) -> None:
    root = tmp_path / "project"
    root.mkdir()
    _project(root, "PUBLIC_MANIFEST\nREADME.md\npyproject.toml\n")
    (root / "README.md").write_text("dirty content\n", encoding="utf-8")
    if staged:
        _git(root, "add", "README.md")

    with pytest.raises(ReleaseBuildError, match="tracked (index|worktree).+clean"):
        build_release(root, tmp_path / "out", tag="v0.1.0-beta.1")


def test_builder_packages_head_blobs_instead_of_hidden_worktree_bytes(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    _project(root, "PUBLIC_MANIFEST\nREADME.md\npyproject.toml\n")
    committed = (root / "README.md").read_bytes()
    _git(root, "update-index", "--assume-unchanged", "README.md")
    (root / "README.md").write_text("hidden dirty content\n", encoding="utf-8")

    artifacts = build_release(root, tmp_path / "out", tag="v0.1.0-beta.1")

    with ZipFile(artifacts.archive) as archive:
        assert archive.read("job-radar-community-v0.1.0-beta.1/README.md") == committed


def test_builder_rejects_a_missing_tested_commit(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    _project(root, "PUBLIC_MANIFEST\nREADME.md\npyproject.toml\n")
    verification_path = root / "docs/verification/v0.1.0-beta.1.json"
    verification = json.loads(verification_path.read_text(encoding="utf-8"))
    verification["tested_product_commit"] = "f" * 40
    verification["test_harness_commit"] = "f" * 40
    _write_verification(root, verification)
    _commit(root, "pin missing commit")

    with pytest.raises(ReleaseBuildError, match="tested commit does not exist"):
        build_release(root, tmp_path / "out", tag="v0.1.0-beta.1")


def test_builder_rejects_a_tested_commit_outside_release_history(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    _project(root, "PUBLIC_MANIFEST\nREADME.md\npyproject.toml\n")
    side_commit = subprocess.run(
        ["git", "commit-tree", _git(root, "rev-parse", "HEAD^{tree}")],
        cwd=root,
        check=True,
        input="side history\n",
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "Release Test",
            "GIT_AUTHOR_EMAIL": "release-test@example.com",
            "GIT_COMMITTER_NAME": "Release Test",
            "GIT_COMMITTER_EMAIL": "release-test@example.com",
        },
    ).stdout.strip()
    verification_path = root / "docs/verification/v0.1.0-beta.1.json"
    verification = json.loads(verification_path.read_text(encoding="utf-8"))
    verification["tested_product_commit"] = side_commit
    verification["test_harness_commit"] = side_commit
    verification_path.write_text(json.dumps(verification), encoding="utf-8")
    _commit(root, "pin side history")

    with pytest.raises(ReleaseBuildError, match="must be an ancestor"):
        build_release(root, tmp_path / "out", tag="v0.1.0-beta.1")


def test_builder_requires_tested_commit_to_be_direct_parent(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    _project(root, "PUBLIC_MANIFEST\nREADME.md\npyproject.toml\n")
    payload = json.loads((root / VERIFICATION_PATH).read_text(encoding="utf-8"))
    payload["verified_at"] = "2026-08-27T22:12:30+02:00"
    _write_verification(root, payload)
    _commit(root, "intermediate evidence-only commit")

    with pytest.raises(ReleaseBuildError, match="direct parent"):
        build_release(root, tmp_path / "out", tag=RELEASE)


def test_builder_requires_both_tested_commit_fields_to_match(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    _project(root, "PUBLIC_MANIFEST\nREADME.md\npyproject.toml\n")
    payload = json.loads((root / VERIFICATION_PATH).read_text(encoding="utf-8"))
    payload["test_harness_commit"] = "f" * 40
    _write_verification(root, payload)
    _commit(root, "split tested commits")

    with pytest.raises(ReleaseBuildError, match="must identify the same commit"):
        build_release(root, tmp_path / "out", tag=RELEASE)


@pytest.mark.parametrize(
    "relative_path",
    ["README.md", "docs/RELEASE_VERIFICATION.md"],
)
def test_builder_rejects_any_change_beside_the_verification_json(
    tmp_path: Path, relative_path: str
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    _project(root, "PUBLIC_MANIFEST\nREADME.md\npyproject.toml\n")
    direct_parent = _git(root, "rev-parse", "HEAD")
    payload = json.loads((root / VERIFICATION_PATH).read_text(encoding="utf-8"))
    payload["tested_product_commit"] = direct_parent
    payload["test_harness_commit"] = direct_parent
    _write_verification(root, payload)
    changed = root / relative_path
    changed.write_text("# changed after verification\n", encoding="utf-8")
    _commit(root, "change content outside verification record")

    with pytest.raises(ReleaseBuildError, match="must change exactly.+verification"):
        build_release(root, tmp_path / "out", tag="v0.1.0-beta.1")


@pytest.mark.parametrize("tag", ["v0.1.0", "v0.1.0-beta.x", "v0.1.0-beta.2"])
def test_builder_requires_matching_beta_tag(tmp_path: Path, tag: str) -> None:
    root = tmp_path / "project"
    root.mkdir()
    _project(root, "PUBLIC_MANIFEST\nREADME.md\npyproject.toml\n")

    with pytest.raises(ReleaseBuildError, match="tag"):
        build_release(root, tmp_path / "out", tag=tag)


def test_builder_cli_runs_as_a_direct_script(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    _project(root, "PUBLIC_MANIFEST\nREADME.md\npyproject.toml\n")
    script = Path(__file__).resolve().parents[1] / "scripts" / "build_release.py"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--source-root",
            str(root),
            "--output-dir",
            str(tmp_path / "out"),
            "--tag",
            "v0.1.0-beta.1",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.count("\n") == 3
