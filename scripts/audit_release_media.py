#!/usr/bin/env python3
"""Audit public WebP captures with deterministic metadata, OCR and PII checks."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import struct
import subprocess
from pathlib import Path
from urllib.parse import urlparse

EXPECTED_CAPTURES = frozenset(
    {"radar-overview.webp", "score-explained.webp", "insights.webp", "mobile.webp"}
)
FORBIDDEN_METADATA = frozenset({"EXIF", "XMP ", "ICCP"})
EXAMPLE_DOMAINS = ("example.com", "example.org", "example.net", "example.invalid")
EMAIL_PATTERN = re.compile(r"(?<![\w.+/-])([\w.+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+))")
URL_PATTERN = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)
PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+33|0)[1-9](?:[ .-]?\d{2}){4}(?!\d)")
PERSONAL_MARKERS = ("jonas", "suhard")


class MediaAuditError(RuntimeError):
    """The capture set cannot produce a trustworthy report."""


def _is_example_domain(domain: str) -> bool:
    domain = domain.casefold().rstrip(".")
    return any(domain == suffix or domain.endswith(f".{suffix}") for suffix in EXAMPLE_DOMAINS)


def _finding(kind: str, value: str) -> dict[str, str]:
    return {"kind": kind, "value_sha256": hashlib.sha256(value.encode()).hexdigest()}


def scan_ocr_text(text: str) -> dict[str, object]:
    """Return redacted PII findings and domains derived from OCR text."""
    findings: list[dict[str, str]] = []
    domains: set[str] = set()
    non_example_domains: set[str] = set()
    folded = text.casefold()

    for email, domain in EMAIL_PATTERN.findall(text):
        normalized = domain.casefold().rstrip(".")
        domains.add(normalized)
        if not _is_example_domain(normalized):
            non_example_domains.add(normalized)
            findings.append(_finding("email", email))
    for raw_url in URL_PATTERN.findall(text):
        domain = (urlparse(raw_url).hostname or "").casefold()
        if domain:
            domains.add(domain)
            if not _is_example_domain(domain):
                non_example_domains.add(domain)
                findings.append(_finding("url", raw_url))
    for phone in PHONE_PATTERN.findall(text):
        findings.append(_finding("phone", phone))
    if ("/" + "users/") in folded:
        findings.append(_finding("personal_path", "/" + "Users/"))
    for marker in PERSONAL_MARKERS:
        if re.search(rf"\b{re.escape(marker)}\b", folded):
            findings.append(_finding("personal_marker", marker))

    return {
        "domains": sorted(domains),
        "non_example_domains": sorted(non_example_domains),
        "pii_findings": sorted(findings, key=lambda item: (item["kind"], item["value_sha256"])),
    }


def _webp_details(content: bytes) -> tuple[tuple[int, int], list[str]]:
    if content[:4] != b"RIFF" or content[8:12] != b"WEBP":
        raise MediaAuditError("capture is not a RIFF WebP image")
    cursor = 12
    dimensions: tuple[int, int] | None = None
    chunks: list[str] = []
    while cursor + 8 <= len(content):
        chunk = content[cursor : cursor + 4]
        size = struct.unpack_from("<I", content, cursor + 4)[0]
        data = content[cursor + 8 : cursor + 8 + size]
        chunks.append(chunk.decode("ascii", errors="replace"))
        if chunk == b"VP8X" and len(data) >= 10:
            dimensions = (
                1 + int.from_bytes(data[4:7], "little"),
                1 + int.from_bytes(data[7:10], "little"),
            )
        elif chunk == b"VP8 " and len(data) >= 10 and data[3:6] == b"\x9d\x01\x2a":
            width, height = struct.unpack_from("<HH", data, 6)
            dimensions = (width & 0x3FFF, height & 0x3FFF)
        elif chunk == b"VP8L" and len(data) >= 5 and data[0] == 0x2F:
            bits = int.from_bytes(data[1:5], "little")
            dimensions = ((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
        cursor += 8 + size + (size % 2)
    if dimensions is None:
        raise MediaAuditError("capture dimensions are unreadable")
    return dimensions, chunks


def _tesseract_major() -> int:
    result = subprocess.run(
        ["tesseract", "--version"], check=True, capture_output=True, text=True
    )
    match = re.search(r"tesseract\s+(\d+)", result.stdout)
    if match is None:
        raise MediaAuditError("cannot determine Tesseract major version")
    return int(match.group(1))


def _ocr(path: Path) -> str:
    environment = {**os.environ, "OMP_THREAD_LIMIT": "1"}
    result = subprocess.run(
        ["tesseract", str(path), "stdout", "-l", "eng"],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    return result.stdout.replace("\r\n", "\n")


def build_media_report(assets_dir: Path) -> dict[str, object]:
    """Recalculate the complete machine report for the four public captures."""
    assets = assets_dir.resolve()
    paths = sorted(assets.glob("*.webp"), key=lambda path: path.name)
    names = {path.name for path in paths}
    if names != EXPECTED_CAPTURES:
        raise MediaAuditError(
            f"capture set mismatch: expected {sorted(EXPECTED_CAPTURES)}, got {sorted(names)}"
        )

    records: list[dict[str, object]] = []
    for path in paths:
        content = path.read_bytes()
        dimensions, chunks = _webp_details(content)
        ocr_result = scan_ocr_text(_ocr(path))
        metadata_findings = sorted(set(chunks) & FORBIDDEN_METADATA)
        records.append(
            {
                "file": path.name,
                "sha256": hashlib.sha256(content).hexdigest(),
                "bytes": len(content),
                "dimensions": list(dimensions),
                "webp_chunks": chunks,
                "metadata_findings": metadata_findings,
                **ocr_result,
            }
        )

    return {
        "schema_version": 1,
        "generator": "scripts/audit_release_media.py",
        "ocr_engine": f"tesseract-{_tesseract_major()}",
        "allowed_domains": list(EXAMPLE_DOMAINS),
        "images": records,
        "summary": {
            "images": len(records),
            "metadata_findings": sum(len(record["metadata_findings"]) for record in records),
            "non_example_domains": sum(
                len(record["non_example_domains"]) for record in records
            ),
            "pii_findings": sum(len(record["pii_findings"]) for record in records),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets-dir", type=Path, default=Path("docs/assets"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", type=Path)
    arguments = parser.parse_args(argv)
    if arguments.output is None and arguments.check is None:
        parser.error("one of --output or --check is required")

    report = build_media_report(arguments.assets_dir)
    rendered = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    if arguments.output is not None:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(rendered, encoding="utf-8")
    if arguments.check is not None:
        expected = arguments.check.read_text(encoding="utf-8")
        if rendered != expected:
            raise MediaAuditError(f"media report is stale: {arguments.check}")
    if report["summary"] != {
        "images": 4,
        "metadata_findings": 0,
        "non_example_domains": 0,
        "pii_findings": 0,
    }:
        raise MediaAuditError("media audit produced findings")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
