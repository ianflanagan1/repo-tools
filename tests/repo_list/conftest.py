"""Fixtures shared by the tests.

Every test starts with HOME pointed inside the test's temporary directory, so no real git config
is read, and an empty `~/projects`, `projects.root`, to be searched. Tests run from outside it.
Bare remotes go in `projects.remotes`, outside the searched folder. The project's config.toml is
`projects.config`, naming the Packagist vendor `me`, and Packagist is faked: see `packagist`.
"""

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

import repo_list
from repo_list import config
from repo_tools.packagist import api as packagist_api


def git(*args: str | Path) -> None:
    subprocess.run(["git", *map(str, args)], check=True, capture_output=True)


class Projects:
    git = staticmethod(git)

    def __init__(self, tmp_path: Path, home: Path) -> None:
        self.root = home / "projects"
        self.remotes = tmp_path / "remotes"
        self.config = tmp_path / "config.toml"
        self.config.write_text('[packagist]\nvendor = "me"\n')
        self.root.mkdir()
        self.remotes.mkdir()

    def local_repo(self, name: str) -> Path:
        """A repository under the root with one commit and no remote."""
        repo = self.root / name
        git("init", "-q", repo)
        self.commit(repo, "init")
        return repo

    def pushed_repo(self, name: str) -> Path:
        """A repository under the root with one commit, pushed to its own bare origin."""
        repo = self.local_repo(name)
        origin = self.origin(repo)
        git("init", "-q", "--bare", origin)
        git("-C", repo, "remote", "add", "origin", origin)
        git("-C", repo, "push", "-qu", "origin", "main")
        return repo

    def origin(self, repo: Path) -> Path:
        return self.remotes / (repo.relative_to(self.root).as_posix().replace("/", "_") + ".git")

    def push_from_elsewhere(self, repo: Path) -> None:
        """Push a new commit to the repo's origin from another clone."""
        elsewhere = self.remotes.parent / "elsewhere"
        git("clone", "-q", self.origin(repo), elsewhere)
        self.commit(elsewhere, "ahead")
        git("-C", elsewhere, "push", "-q")

    def package(self, name: str, vendor: str = "me") -> Path:
        """A pushed repository whose composer.json names it vendor/name."""
        repo = self.pushed_repo(name)
        (repo / "composer.json").write_text(json.dumps({"name": f"{vendor}/{name}"}))
        git("-C", repo, "add", "-A")
        git("-C", repo, "commit", "-qm", "composer.json")
        git("-C", repo, "push", "-q")
        return repo

    @staticmethod
    def commit(repo: Path, message: str) -> None:
        """Add a line to the repo's file f and commit it."""
        with open(repo / "f", "a") as f:
            f.write(message + "\n")
        git("-C", repo, "add", "-A")
        git("-C", repo, "commit", "-qm", message)


@pytest.fixture(autouse=True)
def projects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Projects:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.delenv("NO_COLOR", raising=False)
    git("config", "--global", "user.name", "test")
    git("config", "--global", "user.email", "test@example.com")
    git("config", "--global", "commit.gpgsign", "false")
    git("config", "--global", "init.defaultBranch", "main")
    projects = Projects(tmp_path, home)
    monkeypatch.setattr(config, "CONFIG", projects.config)
    monkeypatch.chdir(tmp_path)
    return projects


class Packagist:
    """A fake of what Packagist lacks of each package it has, kept in a file so that a fake
    packagist command can change it too. A package not in the file isn't on Packagist."""

    def __init__(self, file: Path) -> None:
        self.file = file
        self.file.write_text("{}")

    def lacking(self) -> dict[str, list[str]]:
        return json.loads(self.file.read_text())

    def has(self, package: str, lacking: list[str] | None = None) -> None:
        self.file.write_text(json.dumps(self.lacking() | {package: lacking or []}))

    def lacks(self, package: str, directory: Path) -> list[str] | None:
        return self.lacking().get(package)


@pytest.fixture(autouse=True)
def packagist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Packagist:
    packagist = Packagist(tmp_path / "packagist.json")
    monkeypatch.setattr(packagist_api, "lacks", packagist.lacks)
    return packagist


@dataclass
class Report:
    listing: list[str]
    """The per-repository lines."""
    summary: str
    """The line after them."""
    status: int


@pytest.fixture
def run(capsys: pytest.CaptureFixture[str]):
    """Run repo-list with the given arguments and return its report."""

    def run(*args: str | Path) -> Report:
        status = repo_list.main([str(a) for a in args])
        listing, _, summary = capsys.readouterr().out.rstrip("\n").partition("\n\n")
        return Report(listing.splitlines(), summary, status)

    return run
