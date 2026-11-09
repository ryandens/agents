"""Select PR source for portable OpenGrep scans without container Git credentials."""

import sys
from pathlib import Path

from prepare_datadog_scan import prepare

CONFIG_FILES = (".semgrepignore", ".semgrep.yml", ".semgrep.yaml")


if __name__ == "__main__":
    repo = Path(__file__).resolve().parents[1]
    print(
        prepare(
            repo,
            sys.argv[1],
            sys.argv[2],
            repo / "reports/opengrep-input",
            config_files=CONFIG_FILES,
        ).relative_to(repo)
    )
