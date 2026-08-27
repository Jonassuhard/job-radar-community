#!/usr/bin/env python3
"""Fail-closed checks for private artifacts in the public repository."""

from __future__ import annotations

import re
import subprocess
from argparse import ArgumentParser
from dataclasses import dataclass
from pathlib import Path

FORBIDDEN_COMPONENTS = frozenset({".cloud", ".vercel", "candidatures", "reports"})
FORBIDDEN_SUFFIXES = (".db", ".db-shm", ".db-wal", ".pdf", ".sqlite", ".sqlite3")
IGNORED_DIRECTORIES = frozenset(
    {
        ".git",
        ".nox",
        ".pytest_cache",
        ".ruff_cache",
        ".superpowers",
        ".tox",
        ".venv",
        "__pycache__",
        "artifacts",
        "build",
        "dist",
        "node_modules",
        "playwright-report",
        "test-results",
        "venv",
    }
)
STRICT_RELEASE_FORBIDDEN_DIRECTORIES = (
    frozenset(
        {
            ".coverage",
            "coverage",
            "coverage-report",
            "coverage-reports",
            "htmlcov",
            "reports",
        }
    )
    | IGNORED_DIRECTORIES
)
PERSONAL_MARKERS = tuple(f"PRIVATE_{kind}" for kind in ("PROFILE", "CANDIDATE", "CONTACT"))
EXAMPLE_EMAIL_DOMAINS = ("example.com", "example.org", "example.net", "example.invalid")
EMAIL_PATTERN = re.compile(rb"(?<![\w.+\-/])[\w.+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)")
PERSONAL_PATH_PATTERN = re.compile(re.escape(("/" + "Users/").encode()))
TEXT_CHUNK_SIZE = 64 * 1024
TEXT_OVERLAP_SIZE = 1024


@dataclass(frozen=True, slots=True)
class Finding:
    code: str
    path: Path
    detail: str


def audit_tree(
    root: Path,
    *,
    strict_release: bool = False,
    require_manifest: bool = True,
) -> list[Finding]:
    """Return deterministic findings for content unsafe to publish."""
    root = root.resolve()
    manifest_path = root / "PUBLIC_MANIFEST"
    if require_manifest and not manifest_path.is_file():
        return [Finding("manifest-missing", Path("PUBLIC_MANIFEST"), "required public allowlist is missing")]

    findings: list[Finding] = []
    manifest_roots = _load_manifest(manifest_path) if require_manifest else None
    reported_unlisted_roots: set[str] = set()
    reported_strict_directories: set[Path] = set()

    if manifest_roots is not None:
        for root_name in sorted(_tracked_roots(root) - manifest_roots):
            findings.append(Finding("unlisted-root", Path(root_name), "tracked root is not listed in PUBLIC_MANIFEST"))
            reported_unlisted_roots.add(root_name)

    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative_path = path.relative_to(root)
        strict_directory = _strict_release_directory(relative_path)
        if strict_release and strict_directory is not None:
            if strict_directory not in reported_strict_directories:
                findings.append(
                    Finding(
                        "release-forbidden-directory",
                        strict_directory,
                        "release staging must not contain ignored runtime directories",
                    )
                )
                reported_strict_directories.add(strict_directory)
            continue
        if any(part in IGNORED_DIRECTORIES for part in relative_path.parts):
            continue
        if path.is_dir() and not path.is_symlink():
            continue

        root_name = relative_path.parts[0]
        if (
            manifest_roots is not None
            and
            root_name not in manifest_roots
            and root_name not in reported_unlisted_roots
        ):
            findings.append(Finding("unlisted-root", Path(root_name), "not listed in PUBLIC_MANIFEST"))
            reported_unlisted_roots.add(root_name)

        if path.is_symlink():
            target = path.resolve()
            if not _is_within(target, root):
                findings.append(Finding("external-symlink", relative_path, str(target)))
            continue

        if _is_forbidden_path(relative_path):
            findings.append(Finding("forbidden-path", relative_path, "forbidden public artifact"))
            continue

        if not path.is_file():
            continue

        findings.extend(_audit_text_file(path, relative_path))

    return findings


def _tracked_roots(root: Path) -> set[str]:
    git_directory = root / ".git"
    if not git_directory.exists():
        return set()
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        return set()
    return {
        Path(encoded.decode("utf-8")).parts[0]
        for encoded in result.stdout.split(b"\0")
        if encoded
    }


def _strict_release_directory(path: Path) -> Path | None:
    for index, part in enumerate(path.parts):
        if part in STRICT_RELEASE_FORBIDDEN_DIRECTORIES:
            return Path(*path.parts[: index + 1])
    return None


def _load_manifest(manifest_path: Path) -> set[str]:
    roots: set[str] = set()
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        entry = line.strip().rstrip("/")
        if entry and not entry.startswith("#") and len(Path(entry).parts) == 1:
            roots.add(entry)
    return roots


def _is_forbidden_path(path: Path) -> bool:
    name = path.name.lower()
    if name.startswith(".env") and name != ".env.example":
        return True
    return any(
        part.lower() in FORBIDDEN_COMPONENTS for part in path.parts
    ) or name.endswith(FORBIDDEN_SUFFIXES)


def _audit_text_file(path: Path, relative_path: Path) -> list[Finding]:
    findings: list[Finding] = []
    found_codes: set[str] = set()
    marker_bytes = tuple(marker.encode() for marker in PERSONAL_MARKERS)
    remainder = b""

    with path.open("rb") as file:
        while chunk := file.read(TEXT_CHUNK_SIZE):
            content = remainder + chunk
            if "personal-path" not in found_codes and PERSONAL_PATH_PATTERN.search(content):
                findings.append(Finding("personal-path", relative_path, "contains a /" + "Users/ path"))
                found_codes.add("personal-path")

            if path.name != "LICENSE" and "personal-marker" not in found_codes:
                marker = next((item for item in marker_bytes if item in content), None)
                if marker is not None:
                    findings.append(Finding("personal-marker", relative_path, marker.decode()))
                    found_codes.add("personal-marker")

            if "personal-email" not in found_codes:
                domain = next(
                    (item for item in EMAIL_PATTERN.findall(content) if not _is_example_domain(item.decode().lower())),
                    None,
                )
                if domain is not None:
                    findings.append(Finding("personal-email", relative_path, domain.decode()))
                    found_codes.add("personal-email")

            remainder = content[-TEXT_OVERLAP_SIZE:]

    return findings


def _is_example_domain(domain: str) -> bool:
    return any(domain == suffix or domain.endswith(f".{suffix}") for suffix in EXAMPLE_EMAIL_DOMAINS)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, nargs="?", default=Path("."))
    parser.add_argument(
        "--strict-release",
        action="store_true",
        help="reject directories that are ignored during a working-tree audit",
    )
    arguments = parser.parse_args(argv)
    findings = audit_tree(arguments.root, strict_release=arguments.strict_release)
    for finding in findings:
        print(f"{finding.code}: {finding.path}: {finding.detail}")
    print(f"{len(findings)} finding{'s' if len(findings) != 1 else ''}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
