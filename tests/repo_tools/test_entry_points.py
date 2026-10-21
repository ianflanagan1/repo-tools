"""The github, bitbucket and packagist commands that uv installs into .venv/bin."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

BIN = Path(sys.prefix) / "bin"
COMMANDS = ["github", "bitbucket", "packagist"]


def launch(command: Path, *args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([command, *args], capture_output=True, text=True, cwd=cwd)


@pytest.mark.parametrize("name", COMMANDS)
def test_the_command_runs_from_any_directory(name: str, tmp_path: Path):
    result = launch(BIN / name, "--help", cwd=tmp_path)
    assert result.returncode == 0
    assert result.stdout.startswith(f"usage: {name}")


@pytest.mark.parametrize("name", COMMANDS)
def test_the_command_works_through_a_symlink(name: str, tmp_path: Path):
    os.symlink(BIN / name, tmp_path / name)
    assert launch(tmp_path / name, "--help", cwd=tmp_path).returncode == 0


@pytest.mark.parametrize("name", COMMANDS)
def test_a_failure_prints_only_the_command_error(name: str, tmp_path: Path):
    result = launch(BIN / name, "publish", "missing", cwd=tmp_path)
    assert result.returncode == 1
    assert result.stderr == "⚠️ No such directory: missing.\n"
