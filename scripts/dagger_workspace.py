"""Run the pinned Dagger CLI on source files, keeping ignored host state outside it.

The beta Python runtime reads a module's enclosing context. A clean source
snapshot bounds that context even when the developer checkout has large ignored
directories. CI already has a clean checkout and uses it directly.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {".git", ".claude", ".aws", ".codex", ".agents"}


def generated(path: Path) -> bool:
    if path.as_posix() in {"dagger.toml", "dagger.lock"}:
        return True
    parts = path.parts
    if parts[0] == ".dagger":
        tail = parts[1:]
    elif len(parts) >= 3 and parts[0] == "dagger":
        tail = parts[2:]
    else:
        return False
    return bool(tail) and (
        tail[0] in {"sdk", "clients"}
        or tail in [("pyproject.toml",), ("uv.lock",), ("dagger-module.toml",)]
    )


def contents(path: Path) -> bytes | None:
    return path.read_bytes() if path.is_file() else None


def fingerprint(path: Path) -> str | None:
    data = contents(path)
    return hashlib.sha256(data).hexdigest() if data is not None else None


def main(args: list[str]) -> int:
    version = (ROOT / ".dagger-version").read_text().strip()
    installed = subprocess.check_output(["dagger", "version"], text=True)
    command = ["dagger"]
    if f"version:     {version}\n" not in installed:
        command.append("--x-release")
        command.append(version)
    if (
        os.environ.get("CI") == "true"
        or os.environ.get("DAGGER_USE_HOST_WORKSPACE") == "1"
    ):
        return subprocess.call([*command, *args], cwd=ROOT)

    names = (
        subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=ROOT,
        )
        .decode()
        .split("\0")
    )
    paths = {
        Path(name) for name in names if name and Path(name).parts[0] not in EXCLUDED
    }
    before = {path: fingerprint(ROOT / path) for path in paths if generated(path)}
    with tempfile.TemporaryDirectory(prefix="agents-dagger-") as temporary:
        snapshot = Path(temporary)
        for path in paths:
            source = ROOT / path
            if not source.exists():
                continue  # Include working-tree deletions.
            if not source.resolve().is_relative_to(ROOT):
                raise ValueError(f"source symlink leaves the repository: {path}")
            target = snapshot / path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target, follow_symlinks=False)
        subprocess.run(["git", "init", "-q", str(snapshot)], check=True)
        # The beta module-client loader also uses the process cwd for ambient
        # workspace access; -W alone does not bound that enclosing context.
        # Explicit artifact exports therefore use absolute host paths.
        status = subprocess.call([*command, *args, "-W", str(snapshot)], cwd=snapshot)
        if status != 0:
            return status
        after_paths = {
            path.relative_to(snapshot)
            for path in snapshot.rglob("*")
            if path.is_file() and generated(path.relative_to(snapshot))
        }
        changes = {
            path
            for path in before.keys() | after_paths
            if before.get(path) != fingerprint(snapshot / path)
        }
        for path in changes:
            if fingerprint(ROOT / path) != before.get(path):
                raise RuntimeError(
                    f"file changed during Dagger execution; refusing to overwrite: {path}"
                )
        for path in changes:
            target = ROOT / path
            if (snapshot / path).is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(snapshot / path, target)
            else:
                target.unlink(missing_ok=True)
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
