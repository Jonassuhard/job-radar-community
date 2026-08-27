#!/usr/bin/env python3
"""Safely extract and audit the Python wheel and sdist selected for release."""

from __future__ import annotations

import argparse
import shutil
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

if __package__:
    from .public_audit import Finding, audit_tree
else:
    from public_audit import Finding, audit_tree


class DistributionAuditError(ValueError):
    """A distribution cannot be extracted safely."""


def _safe_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if not path.parts or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise DistributionAuditError(f"unsafe archive path: {name}")
    return path


def _extract_wheel(archive_path: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            relative = _safe_path(member.filename)
            if member.is_dir():
                continue
            target = destination.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(member))


def _extract_sdist(archive_path: Path, destination: Path) -> None:
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive.getmembers():
            relative = _safe_path(member.name)
            if member.issym() or member.islnk() or member.isdev():
                raise DistributionAuditError(f"non-regular archive member: {member.name}")
            if member.isdir():
                continue
            if not member.isfile():
                raise DistributionAuditError(f"unsupported archive member: {member.name}")
            source = archive.extractfile(member)
            if source is None:
                raise DistributionAuditError(f"unreadable archive member: {member.name}")
            target = destination.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read())


def audit_distributions(
    wheel: Path,
    sdist: Path,
    output_dir: Path,
) -> list[Finding]:
    if output_dir.exists() or output_dir.is_symlink():
        raise DistributionAuditError("distribution audit output must not already exist")
    wheel_root = output_dir / "wheel"
    sdist_root = output_dir / "sdist"
    wheel_root.mkdir(parents=True)
    sdist_root.mkdir(parents=True)
    _extract_wheel(wheel, wheel_root)
    _extract_sdist(sdist, sdist_root)
    return [
        *audit_tree(wheel_root, strict_release=True, require_manifest=False),
        *audit_tree(sdist_root, strict_release=True, require_manifest=False),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--sdist", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        findings = audit_distributions(arguments.wheel, arguments.sdist, arguments.output_dir)
    except (DistributionAuditError, OSError, tarfile.TarError, zipfile.BadZipFile) as error:
        shutil.rmtree(arguments.output_dir, ignore_errors=True)
        parser.error(str(error))
    for finding in findings:
        print(f"{finding.code}: {finding.path}: {finding.detail}")
    print(f"{len(findings)} finding{'s' if len(findings) != 1 else ''}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
