import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from job_radar.cli import app
from scripts.public_audit import (
    IGNORED_DIRECTORIES,
    STRICT_RELEASE_FORBIDDEN_DIRECTORIES,
    audit_tree,
)


def _write_manifest(root: Path) -> None:
    roots = ["PUBLIC_MANIFEST", *(path.name for path in root.iterdir())]
    (root / "PUBLIC_MANIFEST").write_text("\n".join(sorted(set(roots))) + "\n", encoding="utf-8")


def test_audit_rejects_private_artifacts(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("TOKEN=secret", encoding="utf-8")
    (tmp_path / "profile.txt").write_text("/" + "Users/example/private", encoding="utf-8")
    _write_manifest(tmp_path)

    findings = audit_tree(tmp_path)

    assert {item.code for item in findings} == {"forbidden-path", "personal-path"}


def test_audit_rejects_named_private_artifacts(tmp_path: Path) -> None:
    for name in ("data.db", "resume.pdf", ".cloud", ".vercel", "candidatures", "reports"):
        (tmp_path / name).write_text("private", encoding="utf-8")
    _write_manifest(tmp_path)

    findings = audit_tree(tmp_path)

    assert {item.code for item in findings} == {"forbidden-path"}


def test_audit_rejects_external_symlink(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("public-looking", encoding="utf-8")
    (tmp_path / "outside-link").symlink_to(outside)
    _write_manifest(tmp_path)

    findings = audit_tree(tmp_path)

    assert [item.code for item in findings] == ["external-symlink"]


def test_audit_rejects_personal_markers_and_non_example_emails(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text(
        "PRIVATE" + "_PROFILE\ncontact@" + "real-company.test",
        encoding="utf-8",
    )
    _write_manifest(tmp_path)

    findings = audit_tree(tmp_path)

    assert {item.code for item in findings} == {"personal-marker", "personal-email"}


def test_audit_allows_license_copyright_and_example_email(tmp_path: Path) -> None:
    (tmp_path / "LICENSE").write_text("Copyright Jonas Suhard", encoding="utf-8")
    (tmp_path / "README.md").write_text("contact@example.com", encoding="utf-8")
    _write_manifest(tmp_path)

    assert audit_tree(tmp_path) == []


def test_audit_rejects_unlisted_manifest_root(tmp_path: Path) -> None:
    (tmp_path / "PUBLIC_MANIFEST").write_text("PUBLIC_MANIFEST\nREADME.md\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("public", encoding="utf-8")
    (tmp_path / "unlisted-root.txt").write_text("not reviewed", encoding="utf-8")

    findings = audit_tree(tmp_path)

    assert [(item.code, item.path) for item in findings] == [
        ("unlisted-root", Path("unlisted-root.txt")),
    ]


def test_audit_rejects_a_missing_manifest(tmp_path: Path) -> None:
    findings = audit_tree(tmp_path)

    assert [item.code for item in findings] == ["manifest-missing"]


def test_audit_scans_markdown_code_blocks(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text(
        "```text\n/" + "Users/jonas/private\n```\n",
        encoding="utf-8",
    )
    _write_manifest(tmp_path)

    findings = audit_tree(tmp_path)

    assert [item.code for item in findings] == ["personal-path"]


def test_audit_scans_large_text_files_in_stream(tmp_path: Path) -> None:
    (tmp_path / "export.txt").write_text(
        "x" * 1_000_001 + "contact@" + "private.test",
        encoding="utf-8",
    )
    _write_manifest(tmp_path)

    findings = audit_tree(tmp_path)

    assert [item.code for item in findings] == ["personal-email"]


def test_strict_release_audit_refuses_ignored_runtime_directories(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("public", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "review-marker.txt").write_text(
        "PRIVATE" + "_PROFILE", encoding="utf-8"
    )
    _write_manifest(tmp_path)

    findings = audit_tree(tmp_path, strict_release=True)

    assert {item.code for item in findings} == {"release-forbidden-directory"}


def test_strict_release_audit_refuses_git_metadata(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("public", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    _write_manifest(tmp_path)

    findings = audit_tree(tmp_path, strict_release=True)

    assert [item.code for item in findings] == ["release-forbidden-directory"]


def test_strict_release_audit_covers_every_working_tree_ignored_directory() -> None:
    assert STRICT_RELEASE_FORBIDDEN_DIRECTORIES.issuperset(IGNORED_DIRECTORIES)


@pytest.mark.parametrize(
    ("runtime_path", "forbidden_directory"),
    [
        ("frontend/test-results/result.json", "frontend/test-results"),
        ("tests/playwright-report/index.html", "tests/playwright-report"),
        ("src/.venv/pyvenv.cfg", "src/.venv"),
        ("src/__pycache__/module.pyc", "src/__pycache__"),
        ("src/.pytest_cache/v/cache/nodeids", "src/.pytest_cache"),
        ("src/.ruff_cache/content", "src/.ruff_cache"),
        ("frontend/coverage/index.html", "frontend/coverage"),
        ("tests/htmlcov/index.html", "tests/htmlcov"),
        ("tests/reports/results.xml", "tests/reports"),
    ],
)
def test_strict_release_audit_refuses_nested_runtime_directories_under_allowlisted_roots(
    tmp_path: Path,
    runtime_path: str,
    forbidden_directory: str,
) -> None:
    artifact = tmp_path / runtime_path
    artifact.parent.mkdir(parents=True)
    artifact.write_text("generated output\n", encoding="utf-8")
    manifest_root = Path(runtime_path).parts[0]
    (tmp_path / "PUBLIC_MANIFEST").write_text(
        f"PUBLIC_MANIFEST\n{manifest_root}/\n",
        encoding="utf-8",
    )

    findings = audit_tree(tmp_path, strict_release=True)

    assert [(item.code, item.path) for item in findings] == [
        ("release-forbidden-directory", Path(forbidden_directory)),
    ]


def test_audit_allows_go_module_versions_and_ignores_empty_untracked_directories(
    tmp_path: Path,
) -> None:
    (tmp_path / "README.md").write_text(
        "go install github.com/gitleaks/gitleaks/v8@v8.30.1\n",
        encoding="utf-8",
    )
    (tmp_path / "empty-untracked").mkdir()
    (tmp_path / "PUBLIC_MANIFEST").write_text(
        "PUBLIC_MANIFEST\nREADME.md\n", encoding="utf-8"
    )

    assert audit_tree(tmp_path) == []


def test_audit_rejects_a_tracked_ignored_root_missing_from_manifest(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("public\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text(".superpowers/\n", encoding="utf-8")
    report = tmp_path / ".superpowers" / "review.md"
    report.parent.mkdir()
    report.write_text("local review\n", encoding="utf-8")
    (tmp_path / "PUBLIC_MANIFEST").write_text(
        ".gitignore\nPUBLIC_MANIFEST\nREADME.md\n", encoding="utf-8"
    )
    subprocess.run(["git", "init", "--quiet"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "add", ".gitignore", "PUBLIC_MANIFEST", "README.md"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(["git", "add", "--force", ".superpowers/review.md"], cwd=tmp_path, check=True)

    findings = audit_tree(tmp_path)

    assert [(item.code, item.path) for item in findings] == [
        ("unlisted-root", Path(".superpowers")),
    ]


def test_cli_help_is_executable() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "Job Radar" in result.output
