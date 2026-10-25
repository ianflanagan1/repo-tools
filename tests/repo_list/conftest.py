"""Fixtures shared by the tests.

Every test starts with HOME pointed inside the test's temporary directory, so no real git config
is read, and an empty `~/projects`, `projects.root`, to be searched. Tests run from outside it.
Bare remotes go in `projects.remotes`, outside the searched directory. The project's config.toml is
`projects.config`, naming the Packagist vendor `me` and the npm scope `@me`. Each repository
made sets its integration, local, in a committed .config/ianf-repo-tools.toml;
`projects.integration` sets another, or none, for the repositories made after it. Packagist and npm
are faked: see `packagist` and `npm`. So is the terminal a choice is made on: with no answers
given to `terminal`, there's none, as when an agent runs the command.
Plugins can be faked too: see `plugin`.
"""

import json
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest
from cli_kit import terminal as cli_terminal
from cli_kit.colour import Style

import repo_list
from repo_list import config
from repo_list.plugin import Log, Plugin, Problem, Stage
from repo_list.scan import Directory
from repo_tools.npmjs import api as npm_api
from repo_tools.packagist import api as packagist_api


def git(*args: str | Path) -> None:
    subprocess.run(["git", *map(str, args)], check=True, capture_output=True)


CONFIG = '[packagist]\nvendor = "me"\n\n[npm]\nscope = "@me"\n'


class Projects:
    git = staticmethod(git)

    def __init__(self, tmp_path: Path, home: Path) -> None:
        self.root = home / "projects"
        self.remotes = tmp_path / "remotes"
        self.config = tmp_path / "config.toml"
        self.config.write_text(CONFIG)
        self.next_integration: str | None = "local"
        self.root.mkdir()
        self.remotes.mkdir()

    def integration(self, integration: str | None) -> None:
        """Sets the integration of the repositories made after this, or with None leaves
        it unset."""
        self.next_integration = integration

    def worktree(self, repo: Path, name: str, *args: str) -> Path:
        """A linked worktree of repo under the root, added with args, such as --detach or
        -b feature."""
        path = self.root / name
        git("-C", repo, "worktree", "add", "-q", *args, path)
        return path

    @staticmethod
    def claude_session(directory: Path, session: str, state: str) -> None:
        """Records a Claude Code session in directory as the worktree-hooks plugin does, with this
        test's own process, which is running, as its pid."""
        git_dir = Path(
            subprocess.run(
                ["git", "-C", str(directory), "rev-parse", "--absolute-git-dir"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
        sessions = git_dir / "claude-sessions"
        sessions.mkdir(exist_ok=True)
        record = {"pid": os.getpid(), "state": state}
        (sessions / f"{session}.json").write_text(json.dumps(record))

    def local_repo(self, name: str) -> Path:
        """A repository under the root with one commit and no remote."""
        repo = self.root / name
        git("init", "-q", repo)
        if self.next_integration:
            (repo / ".config").mkdir()
            settings = f'version = 1\nintegration = "{self.next_integration}"\n'
            (repo / ".config" / "ianf-repo-tools.toml").write_text(settings)
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

    def npm_package(self, name: str, manifest: dict) -> Path:
        """A pushed repository whose package.json is manifest."""
        repo = self.pushed_repo(name)
        (repo / "package.json").write_text(json.dumps(manifest))
        git("-C", repo, "add", "-A")
        git("-C", repo, "commit", "-qm", "package.json")
        git("-C", repo, "push", "-q")
        return repo

    def python_project(self, name: str, pyproject: str) -> Path:
        """A pushed repository whose pyproject.toml is pyproject."""
        repo = self.pushed_repo(name)
        (repo / "pyproject.toml").write_text(pyproject)
        git("-C", repo, "add", "-A")
        git("-C", repo, "commit", "-qm", "pyproject.toml")
        git("-C", repo, "push", "-q")
        return repo

    @staticmethod
    def short_head(repo: Path) -> str:
        """HEAD's abbreviated commit, as repo-list shows a detached HEAD."""
        return subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

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
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
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


class Npm:
    """A fake of the version tags npm lacks of each package it has, kept in a file so that a fake
    npmjs command can change it too. A package not in the file isn't on npm."""

    def __init__(self, file: Path) -> None:
        self.file = file
        self.file.write_text("{}")

    def lacking(self) -> dict[str, list[str]]:
        return json.loads(self.file.read_text())

    def has(self, package: str, lacking: list[str]) -> None:
        self.file.write_text(json.dumps(self.lacking() | {package: lacking}))

    def lacks(self, package: str, directory: Path) -> list[str] | None:
        return self.lacking().get(package)


@pytest.fixture(autouse=True)
def npm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Npm:
    npm = Npm(tmp_path / "npm.json")
    monkeypatch.setattr(npm_api, "lacks", npm.lacks)
    return npm


class Terminal:
    """Where repo-list and repo-fix would ask which option to choose. Given answers, it picks the
    option starting with each in turn; given none, there's no terminal, so nothing is chosen."""

    def __init__(self) -> None:
        self.answers: list[str] = []
        self.prompts: list[str] = []
        self.options: list[str] = []
        self.colour = False
        """Whether the terminal is coloured, as when NO_COLOR isn't set."""

    def answer(self, *answers: str) -> None:
        self.answers.extend(answers)

    def choose(self, prompt: str, options: list[str]) -> int | None:
        self.prompts.append(prompt)
        self.options = options
        if not self.answers:
            return None
        answer = self.answers.pop(0)
        return next(i for i, option in enumerate(options) if option.startswith(answer))


@pytest.fixture(autouse=True)
def terminal(monkeypatch: pytest.MonkeyPatch) -> Terminal:
    terminal = Terminal()
    monkeypatch.setattr(cli_terminal, "choose", terminal.choose)
    monkeypatch.setattr(cli_terminal, "style", lambda: Style(terminal.colour))
    return terminal


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
        listing, _, summary = capsys.readouterr().out.rstrip("\n").rpartition("\n\n")
        return Report(listing.splitlines(), summary, status)

    return run


@dataclass(frozen=True)
class Found:
    what: str

    def describe(self) -> str:
        return self.what


class FakePlugin(Plugin):
    """Finds whatever is in finds, and records each check and fix in calls.

    Its fix fails if fails is set, and otherwise runs then, which may change what other fakes
    find.
    """

    def __init__(
        self,
        name: str,
        calls: list[str],
        stage: Stage | None = None,
        finds: tuple[str, ...] = (),
        checks_directories: bool = False,
    ) -> None:
        self.name = name
        self.calls = calls
        self.stage = stage
        self.finds = finds
        self.checks_directories = checks_directories
        self.git_fails = False
        self.fails = False
        self.then = lambda: None

    def check(self, directory: Directory) -> list[Problem]:
        self.calls.append(f"check {self.name}")
        if self.git_fails:
            raise subprocess.CalledProcessError(128, ["git"])
        return [Found(what) for what in self.finds]

    def fix(self, directory: Directory, problems: list[Problem], log: Log) -> bool:
        self.calls.append(f"fix {self.name}: {', '.join(p.describe() for p in problems)}")
        if self.fails:
            return False
        self.then()
        return True


@pytest.fixture
def calls() -> list[str]:
    """Each check and fix of the plugins plugin makes, in order."""
    return []


@pytest.fixture
def plugin(calls: list[str]) -> Callable[..., FakePlugin]:
    """Makes fake plugins that record their checks and fixes in calls."""

    def plugin(name: str, **settings) -> FakePlugin:
        return FakePlugin(name, calls, **settings)

    return plugin
