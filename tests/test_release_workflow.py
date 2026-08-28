"""Release workflow and publication shell contracts."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tarfile
import tomllib
from pathlib import Path
from zipfile import ZipFile

import pytest

from scripts.finalize_release_attestation import finalize_attestation

ROOT = Path(__file__).resolve().parents[1]
RELEASE_TAG = "v0.1.0-beta.1"


def _release_asset_paths(artifacts: Path) -> dict[str, Path]:
    archive_root = "job-radar-community-v0.1.0-beta.1"
    package_root = "job_radar_community-0.1.0b1"
    return {
        "archive": artifacts / f"{archive_root}.zip",
        "checksum": artifacts / f"{archive_root}.zip.sha256",
        "attestation": artifacts / f"{archive_root}.attestation.json",
        "sbom": artifacts / f"{archive_root}.cdx.json",
        "wheel": artifacts / f"{package_root}-py3-none-any.whl",
        "sdist": artifacts / f"{package_root}.tar.gz",
    }


def _base_attestation(paths: dict[str, Path], release_sha: str) -> dict[str, object]:
    archive_digest = hashlib.sha256(paths["archive"].read_bytes()).hexdigest()
    return {
        "schema_version": 2,
        "release": RELEASE_TAG,
        "status": "local_candidate_verified",
        "verified_at": "2026-08-27T22:12:00+02:00",
        "publication": {
            "status": "not_published",
            "observed_at": "2026-08-27T22:13:00+02:00",
        },
        "release_commit": release_sha,
        "release_tree": "b" * 40,
        "tested_product_commit": "c" * 40,
        "test_harness_commit": "c" * 40,
        "builder_observations": {
            "archive": {
                "file": paths["archive"].name,
                "sha256": archive_digest,
                "bytes": paths["archive"].stat().st_size,
                "files": 1,
            },
            "attestation": {
                "status": "generated_by_build_release",
                "file": paths["attestation"].name,
            },
            "openapi": {
                "status": "passed",
                "document_sha256": "d" * 64,
                "paths": 1,
                "operations": 1,
            },
            "verification_record_integrity": {
                "file": "docs/verification/v0.1.0-beta.1.json",
                "sha256": "e" * 64,
                "contract_file": "docs/verification/v0.1.0-beta.1-contract.json",
                "contract_sha256": "f" * 64,
                "contract_status": "matched",
            },
        },
        "declared_verification": {
            "provenance": "commit-pinned fixture",
            "checks": {"backend_tests": {"passed": 1, "failed": 0}},
            "captures": [{"file": "fixture.webp"}],
        },
    }


def _write_release_assets(artifacts: Path, release_sha: str) -> dict[str, Path]:
    artifacts.mkdir()
    paths = _release_asset_paths(artifacts)
    with ZipFile(paths["archive"], "w") as archive:
        archive.writestr("job-radar-community-v0.1.0-beta.1/README.md", "public\n")
    digest = hashlib.sha256(paths["archive"].read_bytes()).hexdigest()
    paths["checksum"].write_text(
        f"{digest}  {paths['archive'].name}\n", encoding="utf-8"
    )
    paths["attestation"].write_text(
        json.dumps(_base_attestation(paths, release_sha)), encoding="utf-8"
    )
    paths["sbom"].write_text(
        json.dumps({"bomFormat": "CycloneDX", "specVersion": "1.6"}),
        encoding="utf-8",
    )
    with ZipFile(paths["wheel"], "w") as wheel:
        wheel.writestr("job_radar/__init__.py", "VERSION = 'test'\n")
    source_root = artifacts.parent / "sdist-source" / "job_radar_community-0.1.0b1"
    source_root.mkdir(parents=True)
    (source_root / "README.md").write_text("public\n", encoding="utf-8")
    with tarfile.open(paths["sdist"], "w:gz") as sdist:
        sdist.add(source_root, arcname=source_root.name)
    finalize_attestation(
        tag=RELEASE_TAG,
        expected_commit=release_sha,
        attestation=paths["attestation"],
        source_archive=paths["archive"],
        source_checksum=paths["checksum"],
        sbom=paths["sbom"],
        wheel=paths["wheel"],
        sdist=paths["sdist"],
    )
    return paths


def _fake_gh(tmp_path: Path) -> tuple[Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_gh = bin_dir / "gh"
    fake_gh.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$GH_ARGS_FILE\"\n",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    return bin_dir, tmp_path / "gh-args.txt"


def _git_release_repository(tmp_path: Path, *, create_tag: bool = True) -> tuple[Path, str]:
    origin = tmp_path / "origin.git"
    repository = tmp_path / "repository"
    subprocess.run(["git", "init", "--bare", "--quiet", str(origin)], check=True)
    subprocess.run(["git", "init", "--quiet", str(repository)], check=True)
    (repository / "README.md").write_text("release\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repository, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Release Test",
            "-c",
            "user.email=release@example.com",
            "commit",
            "--quiet",
            "-m",
            "release",
        ],
        cwd=repository,
        check=True,
    )
    release_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(["git", "remote", "add", "origin", str(origin)], cwd=repository, check=True)
    subprocess.run(["git", "push", "--quiet", "origin", "HEAD:refs/heads/main"], cwd=repository, check=True)
    if create_tag:
        subprocess.run(["git", "tag", RELEASE_TAG], cwd=repository, check=True)
        subprocess.run(["git", "push", "--quiet", "origin", RELEASE_TAG], cwd=repository, check=True)
    return repository, release_sha


def _publish(
    tmp_path: Path,
    repository: Path,
    artifacts: Path,
    expected_sha: str,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    bin_dir, args_file = _fake_gh(tmp_path)
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/publish_release.sh"), RELEASE_TAG, str(artifacts)],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "GH_REPO": "example/job-radar-community",
            "GH_ARGS_FILE": str(args_file),
            "EXPECTED_RELEASE_SHA": expected_sha,
        },
    )
    return result, args_file


def test_publish_shell_requires_exact_local_and_remote_tag_and_marks_beta(
    tmp_path: Path,
) -> None:
    repository, release_sha = _git_release_repository(tmp_path)
    artifacts = repository / "artifacts"
    paths = _write_release_assets(artifacts, release_sha)

    result, args_file = _publish(tmp_path, repository, artifacts, release_sha)

    assert result.returncode == 0, result.stderr
    arguments = args_file.read_text(encoding="utf-8").splitlines()
    assert arguments[:3] == ["release", "create", "v0.1.0-beta.1"]
    assert {str(path) for path in paths.values()} <= set(arguments)
    assert ["--repo", "example/job-radar-community"] == arguments[
        arguments.index("--repo") : arguments.index("--repo") + 2
    ]
    assert "--prerelease" in arguments
    assert "--latest=false" in arguments
    assert "--verify-tag" in arguments


def test_publish_shell_rejects_text_files_disguised_as_assets(tmp_path: Path) -> None:
    repository, release_sha = _git_release_repository(tmp_path)
    artifacts = repository / "artifacts"
    artifacts.mkdir()
    for path in _release_asset_paths(artifacts).values():
        path.write_text("not an artifact\n", encoding="utf-8")

    result, args_file = _publish(tmp_path, repository, artifacts, release_sha)

    assert result.returncode != 0
    assert not args_file.exists()


@pytest.mark.parametrize("failure", ["missing_tag", "wrong_sha"])
def test_publish_shell_rejects_missing_tag_or_wrong_expected_sha(
    tmp_path: Path, failure: str
) -> None:
    repository, release_sha = _git_release_repository(
        tmp_path, create_tag=failure != "missing_tag"
    )
    artifacts = repository / "artifacts"
    _write_release_assets(artifacts, release_sha)
    expected_sha = "b" * 40 if failure == "wrong_sha" else release_sha

    result, args_file = _publish(
        tmp_path, repository, artifacts, expected_sha
    )

    assert result.returncode != 0
    assert not args_file.exists()


def test_publish_shell_rejects_missing_or_extra_assets(tmp_path: Path) -> None:
    repository, release_sha = _git_release_repository(tmp_path)
    artifacts = repository / "artifacts"
    paths = _write_release_assets(artifacts, release_sha)
    paths["sbom"].unlink()
    (artifacts / "arbitrary.txt").write_text("extra\n", encoding="utf-8")

    result, args_file = _publish(tmp_path, repository, artifacts, release_sha)

    assert result.returncode != 0
    assert not args_file.exists()


@pytest.mark.parametrize("mismatch", ["checksum", "tag", "commit"])
def test_publish_shell_rejects_inconsistent_release_evidence(
    tmp_path: Path, mismatch: str
) -> None:
    repository, release_sha = _git_release_repository(tmp_path)
    artifacts = repository / "artifacts"
    paths = _write_release_assets(artifacts, release_sha)
    if mismatch == "checksum":
        paths["checksum"].write_text(
            f"{'0' * 64}  {paths['archive'].name}\n", encoding="utf-8"
        )
    else:
        evidence = json.loads(paths["attestation"].read_text(encoding="utf-8"))
        evidence["release" if mismatch == "tag" else "release_commit"] = (
            "v9.9.9-beta.9" if mismatch == "tag" else "b" * 40
        )
        paths["attestation"].write_text(json.dumps(evidence), encoding="utf-8")

    result, args_file = _publish(tmp_path, repository, artifacts, release_sha)

    assert result.returncode != 0
    assert not args_file.exists()


@pytest.mark.parametrize("asset_name", ["sbom", "wheel", "sdist"])
def test_publish_shell_rejects_valid_but_altered_bound_asset(
    tmp_path: Path, asset_name: str
) -> None:
    repository, release_sha = _git_release_repository(tmp_path)
    artifacts = repository / "artifacts"
    paths = _write_release_assets(artifacts, release_sha)
    if asset_name == "sbom":
        paths["sbom"].write_text(
            json.dumps(
                {
                    "bomFormat": "CycloneDX",
                    "specVersion": "1.6",
                    "serialNumber": "urn:uuid:changed",
                }
            ),
            encoding="utf-8",
        )
    elif asset_name == "wheel":
        with ZipFile(paths["wheel"], "a") as wheel:
            wheel.writestr("job_radar/changed.py", "CHANGED = True\n")
    else:
        changed_root = repository / "changed-sdist" / "job_radar_community-0.1.0b1"
        changed_root.mkdir(parents=True)
        (changed_root / "README.md").write_text("changed\n", encoding="utf-8")
        with tarfile.open(paths["sdist"], "w:gz") as sdist:
            sdist.add(changed_root, arcname=changed_root.name)

    result, args_file = _publish(
        tmp_path, repository, artifacts, release_sha
    )

    assert result.returncode != 0
    assert not args_file.exists()


@pytest.mark.parametrize("mutation", ["minimal", "extra_field", "extra_asset"])
def test_publish_shell_rejects_malformed_or_extended_attestation(
    tmp_path: Path, mutation: str
) -> None:
    repository, release_sha = _git_release_repository(tmp_path)
    artifacts = repository / "artifacts"
    paths = _write_release_assets(artifacts, release_sha)
    if mutation == "minimal":
        evidence: dict[str, object] = {
            "release": RELEASE_TAG,
            "release_commit": release_sha,
        }
    else:
        evidence = json.loads(paths["attestation"].read_text(encoding="utf-8"))
        if mutation == "extra_field":
            evidence["override"] = True
        else:
            evidence["published_assets"]["arbitrary"] = {
                "file": "arbitrary.txt",
                "media_type": "text/plain",
                "bytes": 0,
                "sha256": hashlib.sha256(b"").hexdigest(),
            }
    paths["attestation"].write_text(json.dumps(evidence), encoding="utf-8")

    result, args_file = _publish(
        tmp_path, repository, artifacts, release_sha
    )

    assert result.returncode != 0
    assert not args_file.exists()


def test_release_workflow_binds_repository_and_audits_python_distributions() -> None:
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    security_workflow = (ROOT / ".github/workflows/security.yml").read_text(
        encoding="utf-8"
    )

    assert "GH_REPO: ${{ github.repository }}" in workflow
    assert "scripts/publish_release.sh" in workflow
    assert "scripts/audit_python_distribution.py" in workflow
    assert "scripts/finalize_release_attestation.py" in workflow
    assert workflow.index("scripts/audit_python_distribution.py") < workflow.index(
        "actions/upload-artifact"
    )
    assert "artifacts/extracted" in workflow
    assert workflow.index("artifacts/extracted") < workflow.index("actions/upload-artifact")
    assert workflow.index("scripts/finalize_release_attestation.py") < workflow.index(
        "actions/upload-artifact"
    )
    assert "actions/setup-go@924ae3a1cded613372ab5595356fb5720e22ba16" in security_workflow
    assert "go install github.com/gitleaks/gitleaks/v8@v8.30.1" in security_workflow
    assert 'gitleaks detect --source . --log-opts="--all" --redact' in security_workflow
    assert "gitleaks/gitleaks-action@" not in security_workflow


def test_publish_job_checks_out_the_release_script_before_running_it() -> None:
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    publish_job = workflow[workflow.index("  publish:") :]

    assert "actions/checkout@" in publish_job
    assert publish_job.index("actions/checkout@") < publish_job.index(
        "bash scripts/publish_release.sh"
    )
    assert "fetch-depth: 0" in publish_job
    assert "fetch-tags: true" in publish_job
    assert "--verify-tag" in (ROOT / "scripts/publish_release.sh").read_text(
        encoding="utf-8"
    )


def test_python_distribution_audit_extracts_wheel_and_sdist(tmp_path: Path) -> None:
    wheel = tmp_path / "job_radar_community-0.1.0b1-py3-none-any.whl"
    with ZipFile(wheel, "w") as archive:
        archive.writestr("job_radar/__init__.py", "VERSION = 'test'\n")
        archive.writestr("job_radar_community-0.1.0b1.dist-info/METADATA", "Metadata-Version: 2.4\n")
    sdist = tmp_path / "job_radar_community-0.1.0b1.tar.gz"
    source_root = tmp_path / "source" / "job_radar_community-0.1.0b1"
    source_root.mkdir(parents=True)
    (source_root / "README.md").write_text("public\n", encoding="utf-8")
    with tarfile.open(sdist, "w:gz") as archive:
        archive.add(source_root, arcname=source_root.name)

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/audit_python_distribution.py"),
            "--wheel",
            str(wheel),
            "--sdist",
            str(sdist),
            "--output-dir",
            str(tmp_path / "extracted"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "extracted" / "wheel" / "job_radar" / "__init__.py").is_file()
    assert (tmp_path / "extracted" / "sdist" / source_root.name / "README.md").is_file()
    assert "0 findings" in result.stdout


def test_python_distribution_audit_rejects_forbidden_content(tmp_path: Path) -> None:
    wheel = tmp_path / "job_radar_community-0.1.0b1-py3-none-any.whl"
    with ZipFile(wheel, "w") as archive:
        archive.writestr("job_radar/__init__.py", "VERSION = 'test'\n")
        archive.writestr(".superpowers/private.md", "local report\n")
    sdist = tmp_path / "job_radar_community-0.1.0b1.tar.gz"
    source_root = tmp_path / "source" / "job_radar_community-0.1.0b1"
    source_root.mkdir(parents=True)
    (source_root / "README.md").write_text("public\n", encoding="utf-8")
    with tarfile.open(sdist, "w:gz") as archive:
        archive.add(source_root, arcname=source_root.name)

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/audit_python_distribution.py"),
            "--wheel",
            str(wheel),
            "--sdist",
            str(sdist),
            "--output-dir",
            str(tmp_path / "extracted"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "release-forbidden-directory: .superpowers" in result.stdout


def test_hatch_excludes_local_superpowers_reports() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert "/.superpowers" in project["tool"]["hatch"]["build"]["exclude"]


def test_local_superpowers_reports_are_ignored_and_untracked() -> None:
    tracked = subprocess.run(
        ["git", "ls-files", ".superpowers"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()

    assert tracked == []
    assert ".superpowers/" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
