"""Fail-closed contract for the local beta verification evidence."""

from __future__ import annotations

import hashlib
import json
import re
import struct
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERIFICATION = ROOT / "docs/verification/v0.1.0-beta.1.json"
CONTRACT = ROOT / "docs/verification/v0.1.0-beta.1-contract.json"
MEDIA_REPORT = ROOT / "docs/verification/v0.1.0-beta.1-media.json"
EXPECTED_CAPTURES = {
    "radar-overview.webp": (1440, 900),
    "score-explained.webp": (1024, 768),
    "insights.webp": (1440, 900),
    "mobile.webp": (390, 844),
}


def _payload() -> dict[str, object]:
    return json.loads(VERIFICATION.read_text(encoding="utf-8"))


def _contract() -> dict[str, object]:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def _webp_dimensions_and_chunks(content: bytes) -> tuple[tuple[int, int], set[bytes]]:
    assert content[:4] == b"RIFF" and content[8:12] == b"WEBP"
    cursor = 12
    chunks: set[bytes] = set()
    dimensions: tuple[int, int] | None = None
    while cursor + 8 <= len(content):
        chunk = content[cursor : cursor + 4]
        size = struct.unpack_from("<I", content, cursor + 4)[0]
        data = content[cursor + 8 : cursor + 8 + size]
        chunks.add(chunk)
        if chunk == b"VP8X" and len(data) >= 10:
            width = 1 + int.from_bytes(data[4:7], "little")
            height = 1 + int.from_bytes(data[7:10], "little")
            dimensions = (width, height)
        elif chunk == b"VP8 " and len(data) >= 10 and data[3:6] == b"\x9d\x01\x2a":
            width, height = struct.unpack_from("<HH", data, 6)
            dimensions = (width & 0x3FFF, height & 0x3FFF)
        elif chunk == b"VP8L" and len(data) >= 5 and data[0] == 0x2F:
            bits = int.from_bytes(data[1:5], "little")
            dimensions = ((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
        cursor += 8 + size + (size % 2)
    assert dimensions is not None
    return dimensions, chunks


def _assert_timestamp(value: object) -> None:
    assert isinstance(value, str)
    parsed = datetime.fromisoformat(value)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() is not None


def test_beta_verification_is_either_minimal_pending_or_commit_pinned() -> None:
    payload = _payload()

    assert payload["schema_version"] == 2
    assert payload["release"] == "v0.1.0-beta.1"
    assert "github_published" not in payload
    assert payload["status"] in {"pending_commit_pin", "local_candidate_verified"}

    if payload["status"] == "pending_commit_pin":
        assert set(payload) == {
            "schema_version",
            "release",
            "status",
            "tested_product_commit",
            "test_harness_commit",
            "verified_at",
            "publication",
            "limitations",
        }
        assert payload["tested_product_commit"] is None
        assert payload["test_harness_commit"] is None
        assert payload["verified_at"] is None
        assert payload["publication"] == {
            "status": "not_observed",
            "observed_at": None,
        }
        assert payload["limitations"]
        return

    for field in ("tested_product_commit", "test_harness_commit"):
        assert re.fullmatch(r"[0-9a-f]{40}", payload[field])
    assert payload["tested_product_commit"] == payload["test_harness_commit"]
    _assert_timestamp(payload["verified_at"])
    assert payload["publication"]["status"] in {"not_published", "published"}
    _assert_timestamp(payload["publication"]["observed_at"])
    assert payload["limitations"]
    assert set(payload["versions"]) >= {"python", "node", "npm", "uv", "playwright"}


def test_beta_verification_records_exact_test_and_audit_counts() -> None:
    payload = _payload()
    contract = _contract()
    checks = contract["expected_checks"]

    assert set(contract) == {
        "schema_version",
        "release",
        "verification_schema_version",
        "expected_environment",
        "expected_versions",
        "expected_checks",
        "expected_captures",
        "expected_limitations",
    }
    assert contract["schema_version"] == 1
    assert contract["release"] == "v0.1.0-beta.1"
    assert contract["verification_schema_version"] == 2
    assert checks["backend_tests"] == {"passed": 336, "failed": 0}
    assert checks["frontend_tests"] == {"passed": 36, "failed": 0}
    assert checks["e2e_tests"] == {"passed": 37, "failed": 0, "skipped": 8}
    assert checks["axe"] == {"routes_scanned": 20, "violations": 0}
    assert checks["responsive"] == {
        "routes_checked": 20,
        "widths": [320, 390, 768, 1024, 1440],
    }
    assert checks["frontend_build"] == {"status": "passed"}
    assert checks["ruff"] == {"findings": 0}
    assert checks["release_build"] == {"runs": 2, "deterministic": True}
    assert checks["openapi"] == {
        "status": "passed",
        "document_sha256": "2e479ace0202fd056823001eb40436a60bd3f4eea7b69478744466cb81547c63",
        "paths": 15,
        "operations": 19,
    }
    for name in (
        "public_tree",
        "git_history",
        "release_archive",
        "python_distributions",
        "npm",
        "python",
        "capture_ocr",
        "capture_metadata",
    ):
        assert checks["audits"][name]["findings"] == 0
    assert checks["audits"]["python_distributions"]["artifacts"] == 2

    if payload["status"] == "pending_commit_pin":
        assert "checks" not in payload
        assert "captures" not in payload
        assert "versions" not in payload
        assert "environment" not in payload
        return

    assert payload["environment"] == contract["expected_environment"]
    assert payload["versions"] == contract["expected_versions"]
    assert payload["checks"] == contract["expected_checks"]
    assert payload["captures"] == contract["expected_captures"]
    assert payload["limitations"] == contract["expected_limitations"]


def test_public_captures_are_small_webp_files_with_matching_checksums() -> None:
    records = {item["file"]: item for item in _contract()["expected_captures"]}
    media = json.loads(MEDIA_REPORT.read_text(encoding="utf-8"))
    media_records = {item["file"]: item for item in media["images"]}
    assert set(records) == set(EXPECTED_CAPTURES)
    assert set(media_records) == set(EXPECTED_CAPTURES)

    for name, dimensions in EXPECTED_CAPTURES.items():
        path = ROOT / "docs/assets" / name
        assert path.is_file()
        assert path.stat().st_size < 700_000
        content = path.read_bytes()
        actual_dimensions, chunks = _webp_dimensions_and_chunks(content)
        assert actual_dimensions == dimensions
        assert chunks.isdisjoint({b"EXIF", b"XMP ", b"ICCP"})
        digest = hashlib.sha256(content).hexdigest()
        assert records[name]["sha256"] == digest
        assert records[name]["bytes"] == path.stat().st_size
        assert records[name]["ocr_pii_findings"] == 0
        assert records[name]["non_example_domains"] == []
        assert records[name]["sha256"] == media_records[name]["sha256"]
        assert records[name]["bytes"] == media_records[name]["bytes"]
        assert records[name]["dimensions"] == media_records[name]["dimensions"]
        assert media_records[name]["metadata_findings"] == []
        assert media_records[name]["pii_findings"] == []
        assert media_records[name]["non_example_domains"] == []
