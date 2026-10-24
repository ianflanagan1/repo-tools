"""The repo-list and repo-fix commands that uv installs into .venv/bin."""

import os
import subprocess
import sys
from pathlib import Path

REPO_LIST = Path(sys.prefix) / "bin" / "repo-list"
REPO_FIX = Path(sys.prefix) / "bin" / "repo-fix"


def launch(command: Path, *args: str | Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([command, *map(str, args)], capture_output=True, text=True)


def test_the_command_runs_repo_list(projects):
    projects.pushed_repo("a")
    result = launch(REPO_LIST, projects.root)
    assert result.stdout == "✔ All 1 clean\n"


def test_the_command_works_through_a_symlink(projects, tmp_path):
    projects.pushed_repo("a")
    os.symlink(REPO_LIST, tmp_path / "rl")
    assert launch(tmp_path / "rl", projects.root).returncode == 0


def test_the_repo_fix_command_runs_repo_fix(projects):
    projects.pushed_repo("a")
    result = launch(REPO_FIX, projects.root)
    assert result.stdout == "✔ All 1 clean\n"
