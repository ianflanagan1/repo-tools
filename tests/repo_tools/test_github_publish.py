"""The checks github publish makes before it touches GitHub."""

import subprocess
from pathlib import Path

import pytest
from cli_kit.errors import Precondition

from repo_tools.github.__main__ import main
from repo_tools.github.commands.publish import publish


def git(directory: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(directory), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "--allow-empty", "-m", "a")
    return tmp_path


def test_fails_for_a_missing_directory(tmp_path: Path):
    with pytest.raises(Precondition, match="No such directory"):
        publish(tmp_path / "missing", "public", None)


def test_fails_for_a_directory_that_is_not_a_git_repository(tmp_path: Path):
    with pytest.raises(Precondition, match="is not a git repository"):
        publish(tmp_path, "public", None)


def test_fails_when_the_work_tree_has_uncommitted_changes(repo: Path):
    (repo / "new.txt").write_text("x")
    with pytest.raises(Precondition, match="Uncommitted changes"):
        publish(repo, "public", None)


def test_fails_when_head_is_detached(repo: Path):
    git(repo, "checkout", "--detach")
    with pytest.raises(Precondition, match="HEAD is detached"):
        publish(repo, "public", None)


def test_reports_a_failure_on_stderr_with_exit_status_1(tmp_path: Path, capsys):
    assert main(["publish", str(tmp_path / "missing")]) == 1
    assert capsys.readouterr().err.startswith("⚠️ No such directory")
