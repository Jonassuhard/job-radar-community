"""Recalculate the versioned OCR and metadata report for public captures."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.audit_release_media import build_media_report, scan_ocr_text

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs/assets"
REPORT = ROOT / "docs/verification/v0.1.0-beta.1-media.json"


def test_versioned_media_report_matches_fresh_ocr_hash_and_metadata_scan() -> None:
    expected = json.loads(REPORT.read_text(encoding="utf-8"))
    assert build_media_report(ASSETS) == expected
    assert expected["summary"] == {
        "images": 4,
        "metadata_findings": 0,
        "non_example_domains": 0,
        "pii_findings": 0,
    }


def test_ocr_scanner_rejects_personal_markers_and_non_example_domains() -> None:
    result = scan_ocr_text(
        "Jonas Suhard "
        + "/"
        + "Users/private user"
        + "@"
        + "company.test https://private.invalid 06 12 34 56 78"
    )

    assert result["non_example_domains"] == ["company.test", "private.invalid"]
    assert {finding["kind"] for finding in result["pii_findings"]} == {
        "email",
        "personal_marker",
        "personal_path",
        "phone",
        "url",
    }
