#!/usr/bin/env bash
set -euo pipefail

tag=${1:?release tag is required}
artifact_dir=${2:-artifacts}
: "${GH_REPO:?GH_REPO is required}"
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repository_root=$(cd "$script_dir/.." && pwd)

if [[ ! $tag =~ ^v([0-9]+)\.([0-9]+)\.([0-9]+)-beta\.([0-9]+)$ ]]; then
  printf 'Invalid beta release tag: %s\n' "$tag" >&2
  exit 2
fi
version=${tag#v}
python_version="${BASH_REMATCH[1]}.${BASH_REMATCH[2]}.${BASH_REMATCH[3]}b${BASH_REMATCH[4]}"
archive_root="job-radar-community-v${version}"
package_root="job_radar_community-${python_version}"

archive="$artifact_dir/$archive_root.zip"
checksum="$artifact_dir/$archive_root.zip.sha256"
attestation="$artifact_dir/$archive_root.attestation.json"
sbom="$artifact_dir/$archive_root.cdx.json"
wheel="$artifact_dir/$package_root-py3-none-any.whl"
sdist="$artifact_dir/$package_root.tar.gz"
assets=("$archive" "$checksum" "$attestation" "$sbom" "$wheel" "$sdist")

if [[ ! -d $artifact_dir || -L $artifact_dir ]]; then
  printf 'Release artifact directory is missing or unsafe: %s\n' "$artifact_dir" >&2
  exit 2
fi
shopt -s nullglob dotglob
entries=("$artifact_dir"/*)
if ((${#entries[@]} != ${#assets[@]})); then
  printf 'Release directory must contain exactly %d assets, found %d\n' \
    "${#assets[@]}" "${#entries[@]}" >&2
  exit 2
fi
for entry in "${entries[@]}"; do
  known=false
  for asset in "${assets[@]}"; do
    if [[ $entry == "$asset" ]]; then
      known=true
      break
    fi
  done
  if [[ $known != true ]]; then
    printf 'Unexpected release asset: %s\n' "$entry" >&2
    exit 2
  fi
done
for asset in "${assets[@]}"; do
  if [[ ! -f $asset || -L $asset ]]; then
    printf 'Expected release asset is missing or unsafe: %s\n' "$asset" >&2
    exit 2
  fi
done

expected_sha=${EXPECTED_RELEASE_SHA:-${GITHUB_SHA:-}}
if [[ -z $expected_sha ]]; then
  expected_sha=$(git rev-parse HEAD 2>/dev/null || true)
fi
if [[ ! $expected_sha =~ ^[0-9a-f]{40}$ ]]; then
  printf 'EXPECTED_RELEASE_SHA or a Git HEAD commit is required\n' >&2
  exit 2
fi
tag_commit=$(git rev-parse --verify "refs/tags/$tag^{commit}" 2>/dev/null || true)
if [[ -z $tag_commit || $tag_commit != "$expected_sha" ]]; then
  printf 'Local release tag is missing or does not identify the expected commit\n' >&2
  exit 2
fi
remote_tags=$(git ls-remote --tags origin "refs/tags/$tag" "refs/tags/$tag^{}" 2>/dev/null || true)
if [[ -z $remote_tags ]] || ! printf '%s\n' "$remote_tags" | awk -v sha="$expected_sha" '$1 == sha { found=1 } END { exit !found }'; then
  printf 'Remote release tag is missing or does not identify the expected commit\n' >&2
  exit 2
fi

PYTHONPATH="$repository_root${PYTHONPATH:+:$PYTHONPATH}" python3 - \
  "$tag" "$expected_sha" "$archive" "$checksum" "$attestation" "$sbom" "$wheel" "$sdist" <<'PY'
import hashlib
import json
import re
import sys
import tarfile
import zipfile
from pathlib import Path

from scripts.finalize_release_attestation import ASSET_TYPES, BASE_ATTESTATION_KEYS

tag, expected_commit, *encoded_paths = sys.argv[1:]
archive, checksum, attestation, sbom, wheel, sdist = map(Path, encoded_paths)

if not zipfile.is_zipfile(archive):
    raise SystemExit("source archive is not a ZIP file")
archive_digest = hashlib.sha256(archive.read_bytes()).hexdigest()
expected_checksum = f"{archive_digest}  {archive.name}\n"
if checksum.read_text(encoding="utf-8") != expected_checksum:
    raise SystemExit("source archive checksum is invalid")

try:
    evidence = json.loads(attestation.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as error:
    raise SystemExit("release attestation is not valid JSON") from error
if not isinstance(evidence, dict) or set(evidence) != BASE_ATTESTATION_KEYS | {
    "published_assets"
}:
    raise SystemExit("release attestation schema is invalid")
try:
    observations = evidence["builder_observations"]
    archive_record = observations["archive"]
    attestation_record = observations["attestation"]
    integrity = observations["verification_record_integrity"]
except (KeyError, TypeError) as error:
    raise SystemExit("release attestation structure is invalid") from error
if evidence.get("schema_version") != 2 or evidence.get("status") != "local_candidate_verified":
    raise SystemExit("release attestation status is invalid")
if evidence.get("release") != tag:
    raise SystemExit("release attestation tag is inconsistent")
if evidence.get("release_commit") != expected_commit:
    raise SystemExit("release attestation commit is inconsistent")
for commit_field in ("release_commit", "release_tree", "tested_product_commit", "test_harness_commit"):
    if not re.fullmatch(r"[0-9a-f]{40}", evidence.get(commit_field, "")):
        raise SystemExit(f"release attestation commit field is invalid: {commit_field}")
if not isinstance(evidence.get("verified_at"), str):
    raise SystemExit("release attestation verification timestamp is invalid")
publication = evidence.get("publication")
if not isinstance(publication, dict) or set(publication) != {"status", "observed_at"}:
    raise SystemExit("release attestation publication observation schema is invalid")
if publication != {
    "status": "not_published",
    "observed_at": publication.get("observed_at"),
}:
    raise SystemExit("release attestation publication observation is invalid")
if not isinstance(publication.get("observed_at"), str):
    raise SystemExit("release attestation publication timestamp is invalid")
if set(observations) != {
    "attestation",
    "archive",
    "openapi",
    "verification_record_integrity",
}:
    raise SystemExit("release builder observations contain missing or extra fields")
if set(archive_record) != {"file", "sha256", "bytes", "files"}:
    raise SystemExit("release attestation archive record schema is invalid")
if (
    archive_record.get("file") != archive.name
    or archive_record.get("sha256") != archive_digest
    or archive_record.get("bytes") != archive.stat().st_size
):
    raise SystemExit("release attestation archive is inconsistent")
if set(attestation_record) != {"status", "file"} or attestation_record != {
    "status": "generated_by_build_release",
    "file": attestation.name,
}:
    raise SystemExit("release attestation filename is inconsistent")
if set(integrity) != {
    "file",
    "sha256",
    "contract_file",
    "contract_sha256",
    "contract_status",
} or integrity.get("contract_status") != "matched":
    raise SystemExit("release verification contract was not matched")
for digest_field in ("sha256", "contract_sha256"):
    if not re.fullmatch(r"[0-9a-f]{64}", integrity.get(digest_field, "")):
        raise SystemExit("release verification integrity digest is invalid")
openapi = observations.get("openapi")
if (
    not isinstance(openapi, dict)
    or set(openapi) != {"status", "document_sha256", "paths", "operations"}
    or openapi.get("status") != "passed"
    or not re.fullmatch(r"[0-9a-f]{64}", openapi.get("document_sha256", ""))
    or not isinstance(openapi.get("paths"), int)
    or not isinstance(openapi.get("operations"), int)
):
    raise SystemExit("release OpenAPI observation is invalid")
declared = evidence.get("declared_verification")
if (
    not isinstance(declared, dict)
    or set(declared) != {"provenance", "checks", "captures"}
    or not isinstance(declared.get("checks"), dict)
    or not declared["checks"]
    or not isinstance(declared.get("captures"), list)
    or not declared["captures"]
):
    raise SystemExit("declared verification schema is invalid")

asset_paths = {
    "source_archive": archive,
    "source_checksum": checksum,
    "sbom": sbom,
    "wheel": wheel,
    "sdist": sdist,
}
published_assets = evidence.get("published_assets")
if not isinstance(published_assets, dict) or set(published_assets) != set(asset_paths):
    raise SystemExit("published asset manifest is incomplete or contains extras")
for name, path in asset_paths.items():
    content = path.read_bytes()
    expected_record = {
        "file": path.name,
        "media_type": ASSET_TYPES[name],
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }
    record = published_assets.get(name)
    if not isinstance(record, dict) or set(record) != set(expected_record):
        raise SystemExit(f"published asset record schema is invalid: {name}")
    if record != expected_record:
        raise SystemExit(f"published asset hash or metadata is inconsistent: {name}")

try:
    bom = json.loads(sbom.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as error:
    raise SystemExit("SBOM is not valid JSON") from error
if bom.get("bomFormat") != "CycloneDX" or not isinstance(bom.get("specVersion"), str):
    raise SystemExit("SBOM is not a CycloneDX document")
if not zipfile.is_zipfile(wheel):
    raise SystemExit("wheel is not a ZIP distribution")
if not tarfile.is_tarfile(sdist):
    raise SystemExit("sdist is not a tar distribution")
PY

gh release create "$tag" "${assets[@]}" \
  --repo "$GH_REPO" \
  --verify-tag \
  --prerelease \
  --latest=false \
  --generate-notes
