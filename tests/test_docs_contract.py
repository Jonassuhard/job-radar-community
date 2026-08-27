"""Contract tests for the public documentation surface."""

from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path
from urllib.request import urlopen
from zipfile import ZipFile

from scripts.build_release import build_candidate_archive

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_DOCUMENTS = (
    "README.md",
    "docs/CONFIGURATION.md",
    "docs/ARCHITECTURE.md",
    "docs/SOURCES_POLICY.md",
    "docs/PRIVACY.md",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "SECURITY.md",
    "SUPPORT.md",
    "CHANGELOG.md",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
)
MARKDOWN_DOCUMENTS = tuple(path for path in REQUIRED_DOCUMENTS if path.endswith(".md"))
RELATIVE_LINK = re.compile(r"(?<!!)\[[^]]+\]\(([^)]+)\)")
RELEASE_TAG = "v0.1.0-beta.1"
RELEASE_DIRECTORY = "job-radar-community-v0.1.0-beta.1"


def _document(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_required_public_documents_exist() -> None:
    assert [path for path in REQUIRED_DOCUMENTS if not (ROOT / path).is_file()] == []


def test_readme_has_a_local_five_minute_quickstart_with_real_commands() -> None:
    readme = _document("README.md")

    for command in (
        "python3.12 -m venv .venv",
        ". .venv/bin/activate",
        "python -m pip install -e .",
        'job-radar demo --data-dir "$PWD/.job-radar"',
        'job-radar serve --data-dir "$PWD/.job-radar"',
        "npm --prefix frontend ci",
        "npm --prefix frontend run dev",
    ):
        assert command in readme


def test_extracted_release_quickstart_uses_the_builder_directory_in_both_terminals(
    tmp_path: Path,
) -> None:
    artifacts = build_candidate_archive(ROOT, tmp_path / "release", tag=RELEASE_TAG)
    extraction = tmp_path / "extracted"
    with ZipFile(artifacts.archive) as archive:
        archive.extractall(extraction)
    release_root = extraction / RELEASE_DIRECTORY
    readme = (release_root / "README.md").read_text(encoding="utf-8")

    assert f"RELEASE={RELEASE_TAG}" in readme
    assert readme.count("cd job-radar-community-$RELEASE") == 2
    assert release_root.is_dir()

    _run(["python3.12", "-m", "venv", ".venv"], release_root)
    python = release_root / ".venv" / "bin" / "python"
    _run([str(python), "-m", "pip", "install", "-e", "."], release_root)
    _run(
        [
            str(release_root / ".venv" / "bin" / "job-radar"),
            "demo",
            "--data-dir",
            str(release_root / ".job-radar"),
        ],
        release_root,
    )

    backend = subprocess.Popen(
        [
            str(release_root / ".venv" / "bin" / "job-radar"),
            "serve",
            "--data-dir",
            str(release_root / ".job-radar"),
        ],
        cwd=release_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    frontend: subprocess.Popen[str] | None = None
    try:
        _wait_for_http("http://127.0.0.1:8000/health")
        _run(["npm", "--prefix", "frontend", "ci"], release_root)
        frontend = subprocess.Popen(
            [
                "npm",
                "--prefix",
                "frontend",
                "run",
                "dev",
            ],
            cwd=release_root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        _wait_for_http("http://127.0.0.1:5173/health")
    finally:
        _stop(frontend)
        _stop(backend)


def test_public_limits_and_manual_source_policy_are_explicit() -> None:
    combined = "\n".join(_document(path).casefold() for path in MARKDOWN_DOCUMENTS)

    for forbidden_scope in (
        "auto-candidature",
        "linkedin",
        "indeed",
        "welcome to the jungle",
        "manual_only",
    ):
        assert forbidden_scope in combined
    assert "cv" in _document("docs/PRIVACY.md").casefold()
    assert "cookies" in _document("SECURITY.md").casefold()
    assert "jetons" in _document("CONTRIBUTING.md").casefold()


def test_configuration_documents_only_effective_scoring_controls() -> None:
    configuration = _document("docs/CONFIGURATION.md")

    for decision in ("reject", "monitor", "review", "prioritize"):
        assert f"`{decision}`" in configuration
    for axis in (
        "role_fit",
        "skills",
        "location",
        "contract",
        "work_mode",
        "language",
        "seniority",
        "required_terms",
        "include_terms",
        "salary",
    ):
        assert f"`{axis}`" in configuration
    for setting in (
        "minimum_confidence",
        "deduplication_similarity",
        "salary_transparency",
        "missing_salary",
        "missing_role_detail",
        "excluded_term",
        "required_term_missing",
    ):
        assert f"`{setting}`" in configuration


def test_design_distinguishes_future_connectors_from_shipped_capabilities() -> None:
    design = _document("docs/design/2026-08-26-public-v1.md")

    assert "Aucun connecteur distant n'est livre dans la V0.1" in design
    assert "Connecteurs autorises :" not in design


def test_security_issue_link_is_an_absolute_public_repository_url() -> None:
    issue_config = _document(".github/ISSUE_TEMPLATE/config.yml")

    assert (
        "https://github.com/Jonassuhard/job-radar-community/security/advisories/new"
        in issue_config
    )
    assert "../../security/advisories/new" not in issue_config


def test_configuration_documents_private_paths_and_active_generations() -> None:
    configuration = _document("docs/CONFIGURATION.md")

    for contract in ("0700", "0600", ".generations", ".current"):
        assert f"`{contract}`" in configuration
    assert "refuse" in configuration.casefold()
    assert "YAML racine" in configuration


def test_env_file_instructions_explicitly_export_variables() -> None:
    configuration = _document("docs/CONFIGURATION.md")

    assert "set -a; source .env; set +a" in configuration
    assert "n'est pas charge automatiquement" in configuration


def test_manual_import_is_documented_on_cli_api_and_limits() -> None:
    documentation = "\n".join(
        _document(path) for path in ("README.md", "docs/CONFIGURATION.md", "docs/SOURCES_POLICY.md")
    )

    for contract in ("job-radar import", "--preview", "/api/import", "2 MiB", "500 offres"):
        assert contract in documentation


def test_quickstart_runtime_directory_is_fully_ignored() -> None:
    gitignore = _document(".gitignore")
    assert ".job-radar/" in gitignore.splitlines()

    for path in (
        ".job-radar/session-token",
        ".job-radar/config/profile.yml",
        ".job-radar/config/search.yml",
    ):
        result = subprocess.run(
            ["git", "-C", str(ROOT), "check-ignore", "--no-index", "--quiet", path],
            check=False,
        )
        assert result.returncode == 0, path


def test_license_and_runtime_notices_are_declared() -> None:
    assert "MIT License" in _document("LICENSE")
    notices = _document("THIRD_PARTY_NOTICES.md")
    for dependency in ("FastAPI", "Pydantic", "React", "Vite"):
        assert dependency in notices


def test_documentation_relative_links_resolve_inside_the_repository() -> None:
    for document in MARKDOWN_DOCUMENTS:
        parent = (ROOT / document).parent
        for target in RELATIVE_LINK.findall(_document(document)):
            target = target.split("#", maxsplit=1)[0].strip()
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            assert (parent / target).resolve().exists(), f"{document}: {target}"


def test_ci_and_release_require_browser_e2e_and_publish_all_evidence_assets() -> None:
    ci = _document(".github/workflows/ci.yml")
    release = _document(".github/workflows/release.yml")
    publish_script = _document("scripts/publish_release.sh")

    for workflow in (ci, release):
        assert "playwright install --with-deps chromium" in workflow
        assert "npm --prefix frontend run test:e2e" in workflow
    assert "audit_release_media.py" in ci
    assert "audit_release_media.py" in release
    assert "scripts/publish_release.sh" in release
    for contract_fragment in (
        "$archive_root.zip",
        "$archive_root.zip.sha256",
        "$archive_root.attestation.json",
        "$archive_root.cdx.json",
        "$package_root-py3-none-any.whl",
        "$package_root.tar.gz",
        "EXPECTED_RELEASE_SHA",
        "contract_status",
        "zipfile.is_zipfile",
        "tarfile.is_tarfile",
        "published_assets",
        "git ls-remote --tags origin",
        "--verify-tag",
    ):
        assert contract_fragment in publish_script
    assert "scripts/finalize_release_attestation.py" in release


def _run(command: list[str], cwd: Path) -> None:
    result = subprocess.run(
        command,
        check=False,
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def _wait_for_http(url: str) -> None:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.2)
    raise AssertionError(f"service did not start: {url}")


def _stop(process: subprocess.Popen[str] | subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
