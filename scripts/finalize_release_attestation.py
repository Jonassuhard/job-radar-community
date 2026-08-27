"""Bind every non-self-referential release asset into the final attestation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

TAG_PATTERN = re.compile(r"^v(?P<base>\d+\.\d+\.\d+)-beta\.(?P<number>\d+)$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
BASE_ATTESTATION_KEYS = frozenset(
    {
        "schema_version",
        "release",
        "status",
        "verified_at",
        "publication",
        "release_commit",
        "release_tree",
        "tested_product_commit",
        "test_harness_commit",
        "builder_observations",
        "declared_verification",
    }
)
ASSET_TYPES = {
    "source_archive": "application/zip",
    "source_checksum": "text/plain; charset=utf-8",
    "sbom": "application/vnd.cyclonedx+json",
    "wheel": "application/zip",
    "sdist": "application/gzip",
}


class FinalizationError(ValueError):
    """The release attestation cannot be finalized safely."""


def finalize_attestation(
    *,
    tag: str,
    expected_commit: str,
    attestation: Path,
    source_archive: Path,
    source_checksum: Path,
    sbom: Path,
    wheel: Path,
    sdist: Path,
) -> None:
    """Validate the base attestation and atomically bind all other release assets."""
    if TAG_PATTERN.fullmatch(tag) is None:
        raise FinalizationError("release tag is invalid")
    if COMMIT_PATTERN.fullmatch(expected_commit) is None:
        raise FinalizationError("expected release commit is invalid")
    try:
        payload = json.loads(attestation.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise FinalizationError("base attestation is not valid JSON") from error
    if not isinstance(payload, dict) or set(payload) != BASE_ATTESTATION_KEYS:
        raise FinalizationError("base attestation schema is invalid")
    if payload.get("release") != tag or payload.get("release_commit") != expected_commit:
        raise FinalizationError("base attestation tag or commit is inconsistent")

    assets = {
        "source_archive": source_archive,
        "source_checksum": source_checksum,
        "sbom": sbom,
        "wheel": wheel,
        "sdist": sdist,
    }
    if len({path.resolve() for path in assets.values()}) != len(assets):
        raise FinalizationError("release asset paths must be distinct")
    records: dict[str, dict[str, object]] = {}
    for name, path in assets.items():
        if not path.is_file() or path.is_symlink():
            raise FinalizationError(f"release asset is missing or unsafe: {name}")
        content = path.read_bytes()
        records[name] = {
            "file": path.name,
            "media_type": ASSET_TYPES[name],
            "bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
    payload["published_assets"] = records

    attestation.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{attestation.name}.", dir=attestation.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o644)
        temporary.replace(attestation)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--attestation", type=Path, required=True)
    parser.add_argument("--source-archive", type=Path, required=True)
    parser.add_argument("--source-checksum", type=Path, required=True)
    parser.add_argument("--sbom", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--sdist", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        finalize_attestation(
            tag=arguments.tag,
            expected_commit=arguments.expected_commit,
            attestation=arguments.attestation,
            source_archive=arguments.source_archive,
            source_checksum=arguments.source_checksum,
            sbom=arguments.sbom,
            wheel=arguments.wheel,
            sdist=arguments.sdist,
        )
    except FinalizationError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
