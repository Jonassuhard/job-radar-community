"""Build a deterministic source release from tracked, allowlisted files."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

if __package__:
    from .public_audit import audit_tree
else:
    from public_audit import audit_tree

TAG_PATTERN = re.compile(r"^v(?P<version>\d+\.\d+\.\d+-beta\.\d+)$")
PYPROJECT_BETA_PATTERN = re.compile(r"^(?P<base>\d+\.\d+\.\d+)b(?P<number>\d+)$")
REGULAR_FILE_MODES = frozenset({"100644", "100755"})
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
VERIFIED_STATUS = "local_candidate_verified"
FINAL_VERIFICATION_KEYS = frozenset(
    {
        "schema_version",
        "release",
        "status",
        "tested_product_commit",
        "test_harness_commit",
        "verified_at",
        "publication",
        "environment",
        "versions",
        "checks",
        "captures",
        "limitations",
    }
)
CONTRACT_KEYS = frozenset(
    {
        "schema_version",
        "release",
        "verification_schema_version",
        "expected_environment",
        "expected_versions",
        "expected_checks",
        "expected_captures",
        "expected_limitations",
    }
)


class ReleaseBuildError(ValueError):
    """The repository cannot produce a safe, deterministic source release."""


@dataclass(frozen=True, slots=True)
class CandidateArchiveArtifacts:
    archive: Path
    checksum: Path
    staging: Path


@dataclass(frozen=True, slots=True)
class ReleaseArtifacts(CandidateArchiveArtifacts):
    attestation: Path


@dataclass(frozen=True, slots=True)
class GitFile:
    mode: str
    object_id: str


@dataclass(frozen=True, slots=True)
class _CandidateBuild:
    artifacts: CandidateArchiveArtifacts
    root: Path
    version: str
    selected: list[tuple[PurePosixPath, GitFile]]
    release_commit: str
    release_tree: str
    archive_digest: str


def build_candidate_archive(
    source_root: Path, output_dir: Path, *, tag: str
) -> CandidateArchiveArtifacts:
    """Build an audited candidate ZIP without claiming final verification."""
    return _build_candidate_archive(
        source_root,
        output_dir,
        tag=tag,
        reserve_attestation_path=False,
    ).artifacts


def build_release(source_root: Path, output_dir: Path, *, tag: str) -> ReleaseArtifacts:
    """Build a verified source release and its external attestation."""
    destination = output_dir.resolve()
    match = TAG_PATTERN.fullmatch(tag)
    if match is None:
        raise ReleaseBuildError("tag must use the form v0.1.0-beta.N")
    final_paths = _release_paths(destination, match["version"])
    if any(path.exists() or path.is_symlink() for path in final_paths):
        raise ReleaseBuildError("release output paths must not already exist")

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{destination.name}-release-", dir=destination.parent
    ) as temporary:
        candidate = _build_candidate_archive(
            source_root,
            Path(temporary) / "output",
            tag=tag,
            reserve_attestation_path=True,
        )
        attestation = candidate.artifacts.archive.with_suffix(".attestation.json")
        _write_attestation(
            root=candidate.root,
            tag=tag,
            version=candidate.version,
            archive=candidate.artifacts.archive,
            archive_digest=candidate.archive_digest,
            file_count=len(candidate.selected),
            destination=attestation,
            selected=candidate.selected,
            staging=candidate.artifacts.staging,
            release_commit=candidate.release_commit,
            release_tree=candidate.release_tree,
        )
        return _promote_release(candidate.artifacts, attestation, destination)


def _release_paths(destination: Path, version: str) -> tuple[Path, Path, Path, Path]:
    archive_root = f"job-radar-community-v{version}"
    return (
        destination / archive_root,
        destination / f"{archive_root}.zip",
        destination / f"{archive_root}.zip.sha256",
        destination / f"{archive_root}.attestation.json",
    )


def _promote_release(
    candidate: CandidateArchiveArtifacts, attestation: Path, destination: Path
) -> ReleaseArtifacts:
    staging, archive, checksum, final_attestation = _release_paths(
        destination,
        candidate.staging.name.removeprefix("job-radar-community-v"),
    )
    destination_created = not destination.exists()
    destination.mkdir(parents=True, exist_ok=True)
    promoted: list[Path] = []
    try:
        for source, target in (
            (candidate.staging, staging),
            (candidate.archive, archive),
            (candidate.checksum, checksum),
            (attestation, final_attestation),
        ):
            source.replace(target)
            promoted.append(target)
    except OSError as error:
        for path in reversed(promoted):
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)
        if destination_created:
            destination.rmdir()
        raise ReleaseBuildError("release artifact promotion failed") from error
    return ReleaseArtifacts(
        staging=staging,
        archive=archive,
        checksum=checksum,
        attestation=final_attestation,
    )


def _build_candidate_archive(
    source_root: Path,
    output_dir: Path,
    *,
    tag: str,
    reserve_attestation_path: bool,
) -> _CandidateBuild:
    root = source_root.resolve()
    _assert_clean_tracked(root)
    release_commit = _git_value(root, "HEAD")
    release_tree = _git_value(root, "HEAD^{tree}")
    tracked_files = _tracked_files(root, release_commit)
    version = _validate_tag(_head_file(root, tracked_files, PurePosixPath("pyproject.toml")), tag)
    archive_root = f"job-radar-community-v{version}"
    manifest_content = _head_file(root, tracked_files, PurePosixPath("PUBLIC_MANIFEST")).decode("utf-8")
    selected = _select_allowlisted_files(tracked_files, manifest_content)

    destination = output_dir.resolve()
    staging = destination / archive_root
    archive = destination / f"{archive_root}.zip"
    checksum = destination / f"{archive_root}.zip.sha256"
    attestation = destination / f"{archive_root}.attestation.json"
    output_paths = [staging, archive, checksum]
    if reserve_attestation_path:
        output_paths.append(attestation)
    if any(path.exists() or path.is_symlink() for path in output_paths):
        raise ReleaseBuildError("release output paths must not already exist")

    staging.mkdir(parents=True)
    for relative_path, git_file in selected:
        target = staging / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(_git_blob(root, git_file.object_id))
        os.chmod(target, 0o755 if git_file.mode == "100755" else 0o644)

    findings = audit_tree(staging, strict_release=True)
    if findings:
        rendered = ", ".join(f"{item.code}: {item.path}" for item in findings)
        raise ReleaseBuildError(f"release staging audit failed: {rendered}")

    _write_deterministic_zip(archive, staging, selected, archive_root)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    checksum.write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    return _CandidateBuild(
        artifacts=CandidateArchiveArtifacts(
            archive=archive,
            checksum=checksum,
            staging=staging,
        ),
        root=root,
        version=version,
        archive_digest=digest,
        selected=selected,
        release_commit=release_commit,
        release_tree=release_tree,
    )


def _write_attestation(
    *,
    root: Path,
    tag: str,
    version: str,
    archive: Path,
    archive_digest: str,
    file_count: int,
    destination: Path,
    selected: list[tuple[PurePosixPath, GitFile]],
    staging: Path,
    release_commit: str,
    release_tree: str,
) -> None:
    verification_relative = PurePosixPath(f"docs/verification/v{version}.json")
    contract_relative = PurePosixPath(f"docs/verification/v{version}-contract.json")
    if verification_relative not in {path for path, _mode in selected}:
        raise ReleaseBuildError("release verification JSON must be included in the archive")
    if contract_relative not in {path for path, _mode in selected}:
        raise ReleaseBuildError("release verification contract must be included in the archive")
    verification_path = staging / verification_relative
    contract_path = staging / contract_relative
    verification = _read_json_object(verification_path, "release verification JSON")
    contract = _read_json_object(contract_path, "release verification contract")
    verified_at, publication = _validate_verification_record(
        verification,
        contract,
        tag=tag,
        staging=staging,
        version=version,
    )
    tested_product_commit = _verification_commit(verification, "tested_product_commit")
    test_harness_commit = _verification_commit(verification, "test_harness_commit")
    if tested_product_commit != test_harness_commit:
        raise ReleaseBuildError(
            "tested_product_commit and test_harness_commit must identify the same commit"
        )
    _validate_tested_commit(
        root,
        release_commit,
        tested_product_commit,
        verification_relative=verification_relative,
    )

    openapi_result = subprocess.run(
        [sys.executable, str(staging / "scripts/export_openapi.py")],
        cwd=staging,
        check=False,
        capture_output=True,
    )
    if openapi_result.returncode != 0:
        raise ReleaseBuildError("OpenAPI export failed while writing attestation")
    try:
        openapi = json.loads(openapi_result.stdout)
    except json.JSONDecodeError as error:
        raise ReleaseBuildError("OpenAPI export is not valid JSON") from error
    paths = openapi.get("paths")
    if not isinstance(paths, dict):
        raise ReleaseBuildError("OpenAPI export has no paths object")
    operations = sum(
        1
        for path_item in paths.values()
        if isinstance(path_item, dict)
        for method in path_item
        if method in {"get", "post", "put", "patch", "delete", "options", "head"}
    )
    expected_openapi = contract["expected_checks"]["openapi"]
    observed_openapi = {
        "status": "passed",
        "document_sha256": hashlib.sha256(openapi_result.stdout).hexdigest(),
        "paths": len(paths),
        "operations": operations,
    }
    if observed_openapi != expected_openapi:
        raise ReleaseBuildError("recomputed OpenAPI does not match the release contract")

    payload = {
        "schema_version": 2,
        "release": tag,
        "status": verification["status"],
        "verified_at": verified_at,
        "publication": publication,
        "release_commit": release_commit,
        "release_tree": release_tree,
        "tested_product_commit": tested_product_commit,
        "test_harness_commit": test_harness_commit,
        "builder_observations": {
            "attestation": {
                "status": "generated_by_build_release",
                "file": destination.name,
            },
            "archive": {
                "file": archive.name,
                "sha256": archive_digest,
                "bytes": archive.stat().st_size,
                "files": file_count,
            },
            "openapi": observed_openapi,
            "verification_record_integrity": {
                "file": verification_relative.as_posix(),
                "sha256": hashlib.sha256(verification_path.read_bytes()).hexdigest(),
                "contract_file": contract_relative.as_posix(),
                "contract_sha256": hashlib.sha256(contract_path.read_bytes()).hexdigest(),
                "contract_status": "matched",
            },
        },
        "declared_verification": {
            "provenance": (
                "Copied from the commit-pinned verification record after exact contract "
                "validation; the release builder did not execute these tests or audits."
            ),
            "checks": verification["checks"],
            "captures": verification["captures"],
        },
    }
    destination.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def _git_value(root: Path, revision: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", revision],
        check=False,
        capture_output=True,
        text=True,
    )
    value = result.stdout.strip()
    if result.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ReleaseBuildError(f"cannot resolve release Git revision: {revision}")
    return value


def _verification_commit(verification: dict[str, object], field: str) -> str:
    value = verification.get(field)
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ReleaseBuildError(f"release verification JSON must pin {field}")
    return value


def _verification_timestamp(verification: dict[str, object], field: str) -> str:
    value = verification.get(field)
    if not isinstance(value, str):
        raise ReleaseBuildError(f"release verification JSON must timestamp {field}")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ReleaseBuildError(
            f"release verification JSON must timestamp {field} with ISO 8601"
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ReleaseBuildError(
            f"release verification JSON must timestamp {field} with a timezone"
        )
    if parsed > datetime.now(UTC):
        raise ReleaseBuildError(
            f"release verification JSON must not timestamp {field} in the future"
        )
    return value


def _publication_observation(verification: dict[str, object]) -> dict[str, str]:
    publication = verification.get("publication")
    if not isinstance(publication, dict):
        raise ReleaseBuildError("release verification JSON must record publication")
    if set(publication) != {"status", "observed_at"}:
        raise ReleaseBuildError(
            "release verification publication must contain status and observed_at"
        )
    status = publication.get("status")
    if status != "not_published":
        raise ReleaseBuildError(
            "local candidate publication status must be not_published"
        )
    observed_at = _verification_timestamp(publication, "observed_at")
    return {"status": status, "observed_at": observed_at}


def _read_json_object(path: Path, label: str) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReleaseBuildError(f"{label} is unreadable") from error
    if not isinstance(payload, dict):
        raise ReleaseBuildError(f"{label} must be an object")
    return payload


def _require_exact_keys(
    payload: dict[str, object], expected: frozenset[str], label: str
) -> None:
    if set(payload) != expected:
        missing = sorted(expected - set(payload))
        unknown = sorted(set(payload) - expected)
        details = ", ".join([*(f"missing {name}" for name in missing), *(f"unknown {name}" for name in unknown)])
        raise ReleaseBuildError(
            f"{label} contains missing or unknown fields: {details}"
        )


def _validate_verification_record(
    verification: dict[str, object],
    contract: dict[str, object],
    *,
    tag: str,
    staging: Path,
    version: str,
) -> tuple[str, dict[str, str]]:
    _require_exact_keys(contract, CONTRACT_KEYS, "release verification contract")
    if contract.get("schema_version") != 1 or contract.get("release") != tag:
        raise ReleaseBuildError("release verification contract does not match the tag")
    if contract.get("verification_schema_version") != 2:
        raise ReleaseBuildError("release verification contract requires an unknown schema")

    if verification.get("release") != tag:
        raise ReleaseBuildError("release verification JSON does not match the tag")
    if verification.get("schema_version") != contract["verification_schema_version"]:
        raise ReleaseBuildError("release verification JSON must use schema_version 2")
    if verification.get("status") != VERIFIED_STATUS:
        raise ReleaseBuildError(
            f"release verification JSON status must be {VERIFIED_STATUS}"
        )
    _require_exact_keys(verification, FINAL_VERIFICATION_KEYS, "release verification JSON")

    verified_at = _verification_timestamp(verification, "verified_at")
    publication = _publication_observation(verification)
    if datetime.fromisoformat(publication["observed_at"]) < datetime.fromisoformat(verified_at):
        raise ReleaseBuildError("publication observation cannot predate verification")

    for field in ("environment", "versions", "checks", "captures", "limitations"):
        if verification.get(field) != contract.get(f"expected_{field}"):
            raise ReleaseBuildError(
                f"release verification {field} does not match the immutable contract"
            )

    expected_checks = contract.get("expected_checks")
    if not isinstance(expected_checks, dict) or not isinstance(
        expected_checks.get("openapi"), dict
    ):
        raise ReleaseBuildError("release verification contract checks are invalid")

    _validate_capture_evidence(
        staging,
        version=version,
        captures=verification["captures"],
    )
    return verified_at, publication


def _validate_capture_evidence(
    staging: Path, *, version: str, captures: object
) -> None:
    if not isinstance(captures, list) or not captures:
        raise ReleaseBuildError("release verification captures must be a non-empty list")
    media_path = staging / f"docs/verification/v{version}-media.json"
    media = _read_json_object(media_path, "release media report")
    images = media.get("images")
    if not isinstance(images, list):
        raise ReleaseBuildError("release media report images must be a list")
    media_by_name = {
        item.get("file"): item for item in images if isinstance(item, dict)
    }
    if len(media_by_name) != len(images):
        raise ReleaseBuildError("release media report contains invalid or duplicate images")

    expected_names: set[str] = set()
    for capture in captures:
        if not isinstance(capture, dict):
            raise ReleaseBuildError("release verification capture must be an object")
        _require_exact_keys(
            capture,
            frozenset(
                {
                    "file",
                    "sha256",
                    "bytes",
                    "dimensions",
                    "ocr_pii_findings",
                    "non_example_domains",
                }
            ),
            "release verification capture",
        )
        name = capture.get("file")
        if not isinstance(name, str) or PurePosixPath(name).name != name:
            raise ReleaseBuildError("release verification capture filename is unsafe")
        expected_names.add(name)
        media_record = media_by_name.get(name)
        if not isinstance(media_record, dict):
            raise ReleaseBuildError("release verification capture is absent from media report")
        if any(
            media_record.get(field) != capture.get(field)
            for field in ("sha256", "bytes", "dimensions", "non_example_domains")
        ):
            raise ReleaseBuildError("release verification capture does not match media report")
        if (
            capture.get("ocr_pii_findings") != 0
            or media_record.get("metadata_findings") != []
            or media_record.get("pii_findings") != []
            or media_record.get("non_example_domains") != []
        ):
            raise ReleaseBuildError("release verification capture has privacy findings")
        asset = staging / "docs" / "assets" / name
        try:
            content = asset.read_bytes()
        except OSError as error:
            raise ReleaseBuildError("release verification capture file is unreadable") from error
        if len(content) != capture.get("bytes") or hashlib.sha256(content).hexdigest() != capture.get(
            "sha256"
        ):
            raise ReleaseBuildError("release verification capture bytes do not match evidence")

    if expected_names != set(media_by_name):
        raise ReleaseBuildError("release media report image set does not match the contract")
    summary = media.get("summary")
    if summary != {
        "images": len(captures),
        "metadata_findings": 0,
        "non_example_domains": 0,
        "pii_findings": 0,
    }:
        raise ReleaseBuildError("release media report summary is not clean")


def _validate_tested_commit(
    root: Path,
    release_commit: str,
    tested_commit: str,
    *,
    verification_relative: PurePosixPath,
) -> None:
    exists = subprocess.run(
        ["git", "-C", str(root), "cat-file", "-e", f"{tested_commit}^{{commit}}"],
        check=False,
        capture_output=True,
    )
    if exists.returncode != 0:
        raise ReleaseBuildError("tested commit does not exist in the repository")
    ancestor = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", tested_commit, release_commit],
        check=False,
        capture_output=True,
    )
    if ancestor.returncode != 0:
        raise ReleaseBuildError("tested commit must be an ancestor of the release commit")
    parent = _git_value(root, f"{release_commit}^")
    if parent != tested_commit:
        raise ReleaseBuildError(
            "tested commit must be the direct parent of the release commit"
        )

    changed = _changed_paths(root, tested_commit, release_commit)
    expected = [verification_relative.as_posix()]
    if changed != expected:
        rendered = ", ".join(changed[:5]) or "no changed path"
        raise ReleaseBuildError(
            "tested commit to release commit must change exactly "
            f"{verification_relative}: {rendered}"
        )


def _changed_paths(root: Path, ancestor: str, release_commit: str) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(root), "diff", "--name-only", "-z", ancestor, release_commit],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise ReleaseBuildError("cannot compare tested commits with the release")
    return sorted(path.decode("utf-8") for path in result.stdout.split(b"\0") if path)


def _validate_tag(pyproject_content: bytes, tag: str) -> str:
    match = TAG_PATTERN.fullmatch(tag)
    if match is None:
        raise ReleaseBuildError("tag must use the form v0.1.0-beta.N")
    try:
        project = tomllib.loads(pyproject_content.decode("utf-8"))
        package_version = project["project"]["version"]
    except (FileNotFoundError, KeyError, tomllib.TOMLDecodeError) as error:
        raise ReleaseBuildError("pyproject.toml must define project.version") from error
    if not isinstance(package_version, str):
        raise ReleaseBuildError("pyproject project.version must be a string")
    package_match = PYPROJECT_BETA_PATTERN.fullmatch(package_version)
    if package_match is None:
        raise ReleaseBuildError("pyproject project.version must use 0.1.0b1 beta syntax")
    expected = f"{package_match['base']}-beta.{package_match['number']}"
    if match["version"] != expected:
        raise ReleaseBuildError("tag does not match pyproject project.version")
    return match["version"]


def _assert_clean_tracked(root: Path) -> None:
    result = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain=v1", "-z", "--untracked-files=no"],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise ReleaseBuildError("source root must be a Git working tree")
    if result.stdout:
        raise ReleaseBuildError("tracked index and worktree must be clean before release")


def _tracked_files(root: Path, revision: str) -> dict[PurePosixPath, GitFile]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-tree", "-r", "-z", "--full-tree", revision],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise ReleaseBuildError("source root must be a Git working tree")
    tracked: dict[PurePosixPath, GitFile] = {}
    for entry in result.stdout.split(b"\0"):
        if not entry:
            continue
        metadata, encoded_path = entry.split(b"\t", maxsplit=1)
        mode, _object_type, object_id = metadata.decode("ascii").split()
        path = PurePosixPath(encoded_path.decode("utf-8"))
        tracked[path] = GitFile(mode=mode, object_id=object_id)
    return tracked


def _head_file(
    root: Path,
    tracked: dict[PurePosixPath, GitFile],
    path: PurePosixPath,
) -> bytes:
    git_file = tracked.get(path)
    if git_file is None or git_file.mode not in REGULAR_FILE_MODES:
        raise ReleaseBuildError(f"required release file is absent from HEAD: {path}")
    return _git_blob(root, git_file.object_id)


def _git_blob(root: Path, object_id: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), "cat-file", "blob", object_id],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise ReleaseBuildError(f"cannot read Git blob: {object_id}")
    return result.stdout


def _select_allowlisted_files(
    tracked: dict[PurePosixPath, GitFile], manifest_content: str
) -> list[tuple[PurePosixPath, GitFile]]:
    selected: dict[PurePosixPath, GitFile] = {}
    seen_entries: set[PurePosixPath] = set()
    for raw_line in manifest_content.splitlines():
        raw_entry = raw_line.strip()
        if not raw_entry or raw_entry.startswith("#"):
            continue
        entry, directory = _validate_manifest_entry(raw_entry)
        if entry in seen_entries:
            raise ReleaseBuildError(f"PUBLIC_MANIFEST duplicates {raw_entry}")
        seen_entries.add(entry)
        matches = [
            (path, git_file)
            for path, git_file in tracked.items()
            if (path.is_relative_to(entry) if directory else path == entry)
        ]
        if not matches:
            raise ReleaseBuildError(f"PUBLIC_MANIFEST entry is absent from Git: {raw_entry}")
        for path, git_file in matches:
            if git_file.mode == "120000":
                raise ReleaseBuildError(f"tracked symlink is forbidden: {path}")
            if git_file.mode == "160000":
                raise ReleaseBuildError(f"tracked submodule is forbidden: {path}")
            if git_file.mode not in REGULAR_FILE_MODES:
                raise ReleaseBuildError(f"tracked file mode is unsupported: {path}")
            selected[path] = git_file
    return sorted(selected.items(), key=lambda item: item[0].as_posix())


def _validate_manifest_entry(raw_entry: str) -> tuple[PurePosixPath, bool]:
    if "\\" in raw_entry or "#" in raw_entry:
        raise ReleaseBuildError(f"PUBLIC_MANIFEST entry is invalid: {raw_entry}")
    directory = raw_entry.endswith("/")
    entry = PurePosixPath(raw_entry.rstrip("/"))
    if (
        not entry.parts
        or entry.is_absolute()
        or any(part in {"", ".", ".."} for part in entry.parts)
    ):
        raise ReleaseBuildError(f"PUBLIC_MANIFEST entry is unsafe: {raw_entry}")
    return entry, directory


def _write_deterministic_zip(
    archive: Path,
    staging: Path,
    selected: list[tuple[PurePosixPath, GitFile]],
    archive_root: str,
) -> None:
    with zipfile.ZipFile(
        archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9, strict_timestamps=True
    ) as bundle:
        for relative_path, git_file in selected:
            entry = zipfile.ZipInfo(f"{archive_root}/{relative_path.as_posix()}")
            entry.date_time = ZIP_TIMESTAMP
            entry.create_system = 3
            entry.external_attr = (
                (0o755 if git_file.mode == "100755" else 0o644) & 0xFFFF
            ) << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(entry, (staging / relative_path).read_bytes())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=Path("."))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    arguments = parser.parse_args(argv)
    try:
        artifacts = build_release(arguments.source_root, arguments.output_dir, tag=arguments.tag)
    except ReleaseBuildError as error:
        parser.error(str(error))
    print(artifacts.archive)
    print(artifacts.checksum)
    print(artifacts.attestation)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
