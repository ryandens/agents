import subprocess

from prepare_datadog_scan import prepare


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root).decode().strip()


def commit(root):
    git(root, "add", ".")
    git(
        root,
        "-c",
        "commit.gpgsign=false",
        "-c",
        "user.name=fixture",
        "-c",
        "user.email=fixture@example.com",
        "commit",
        "-qm",
        "fixture",
    )
    return git(root, "rev-parse", "HEAD")


def test_diff_preserves_paths_ignores_and_renames(tmp_path):
    git(tmp_path, "init", "-q")
    (tmp_path / "code-security.datadog.yaml").write_text("schema-version: v1.0\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "src/.gitignore").write_text("generated.py\n")
    (tmp_path / "src/old.py").write_text("print('rename')\n")
    (tmp_path / "deleted.py").write_text("print('delete')\n")
    base = commit(tmp_path)
    (tmp_path / "src/old.py").rename(tmp_path / "src/new file.py")
    (tmp_path / "deleted.py").unlink()
    head = commit(tmp_path)
    output = prepare(tmp_path, base, head, tmp_path / "scan")
    assert (output / "src/new file.py").read_text() == "print('rename')\n"
    assert (output / "src/.gitignore").is_file()
    assert not (output / "deleted.py").exists()
    assert not (output / "src/old.py").exists()


def test_configuration_changes_require_full_scan(tmp_path):
    git(tmp_path, "init", "-q")
    (tmp_path / "code-security.datadog.yaml").write_text("schema-version: v1.0\n")
    base = commit(tmp_path)
    (tmp_path / "code-security.datadog.yaml").write_text(
        "schema-version: v1.0\n# new rules\n"
    )
    head = commit(tmp_path)
    assert prepare(tmp_path, base, head, tmp_path / "scan") == tmp_path


def test_empty_diff_produces_a_config_only_scan(tmp_path):
    git(tmp_path, "init", "-q")
    (tmp_path / "code-security.datadog.yaml").write_text("schema-version: v1.0\n")
    ref = commit(tmp_path)
    output = prepare(tmp_path, ref, ref, tmp_path / "scan")
    assert sorted(path.name for path in output.iterdir()) == [
        "code-security.datadog.yaml"
    ]


def test_deleted_ignore_file_requires_full_scan(tmp_path):
    git(tmp_path, "init", "-q")
    (tmp_path / ".gitignore").write_text("generated.py\n")
    base = commit(tmp_path)
    (tmp_path / ".gitignore").unlink()
    head = commit(tmp_path)
    assert prepare(tmp_path, base, head, tmp_path / "scan") == tmp_path
