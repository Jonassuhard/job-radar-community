"""Print a stable OpenAPI document without touching user configuration."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


def export_openapi() -> str:
    project_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project_root / "src"))
    from job_radar.api.app import ApiSettings, create_app
    from job_radar.config.loader import initialize_config

    with tempfile.TemporaryDirectory(prefix="job-radar-openapi-") as directory:
        root = Path(directory)
        initialize_config(root / "config")
        application = create_app(ApiSettings(data_dir=root, config_dir=root / "config"))
        return (
            json.dumps(
                application.openapi(),
                indent=2,
                sort_keys=True,
                ensure_ascii=True,
            )
            + "\n"
        )


if __name__ == "__main__":
    sys.stdout.write(export_openapi())
