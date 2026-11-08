"""Prepare the same path-preserving PR scan locally and in CI."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def prepare(repo: Path, base: str, head: str, destination: Path) -> Path:
    root = repo.resolve()
    output = destination.resolve()
    if output == root or not output.is_relative_to(root):
        raise ValueError("scan output must be a subdirectory of the repository")
    refs = [
        subprocess.check_output(
            ["git", "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"],
            cwd=root,
        )
        .decode()
        .strip()
        for ref in (base, head)
    ]
    changed = (
        subprocess.check_output(
            ["git", "diff", "--name-only", "-z", *refs],
            cwd=root,
        )
        .decode()
        .split("\0")
    )
    paths = [Path(name) for name in changed if name]
    if any(
        path.name in {"code-security.datadog.yaml", ".gitignore", ".gitattributes"}
        for path in paths
    ):
        return root  # Rules and exclusion changes can affect otherwise unchanged files.
    output.mkdir(parents=True, exist_ok=False)
    inputs = {
        Path("code-security.datadog.yaml"),
        Path(".gitignore"),
        Path(".gitattributes"),
    }
    for path in paths:
        inputs.add(path)
        for parent in path.parents:
            inputs.update({parent / ".gitignore", parent / ".gitattributes"})
    for path in inputs:
        source = root / path
        if not source.is_file() or source.is_symlink():
            continue
        if not source.resolve().is_relative_to(root):
            raise ValueError(f"scan input leaves the repository: {path}")
        target = output / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return output


if __name__ == "__main__":
    repo = Path(__file__).resolve().parents[1]
    print(
        prepare(
            repo, sys.argv[1], sys.argv[2], repo / "reports/datadog-input"
        ).relative_to(repo)
    )
