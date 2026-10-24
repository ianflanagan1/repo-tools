"""Finding the repositories under a directory, and what the plugins find in each that needs
attention.

Shared by repo-list, which reports the problems, and repo-fix, which fixes them.
"""

import subprocess
import tomllib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import final

from git_default_branch import default_branch

from repo_list import agents
from repo_list.config import Invalid, integration_in
from repo_list.git import batch_env, git
from repo_list.integration import Integration, Worktree, mode_icon
from repo_list.plugin import Badge, Note, Plugin, Problem, Slot

WORKERS = 8
FETCH_TIMEOUT_SECONDS = 60
WORKSPACE = ".workspace.toml"
WORKSPACE_TABLE = "repo-tools"
NO_MODE = f"Set `integration` in {WORKSPACE} under [{WORKSPACE_TABLE}]"
"""The table of repo-tools' settings in a repository's .workspace.toml, which its team shares."""


@dataclass(frozen=True)
class FetchFailed:
    def describe(self) -> str:
        return "📡 fetch failed"


@dataclass(frozen=True)
class GitFailed:
    """git couldn't read the repository."""

    def describe(self) -> str:
        return "💥 git failed"


@dataclass(frozen=True)
class ConfigInvalid:
    """The repository's .workspace.toml has a repo-tools setting that can't be used."""

    message: str

    def describe(self) -> str:
        return f"🔧 {self.message}"


WORKING = Note("🤖 Claude working")
"""A Claude Code session is busy in the directory, so repo-fix leaves it alone."""


@final
@dataclass(frozen=True)
class Place:
    """Where a repository's directory stands among the worktrees of its repository, and what it
    integrates into."""

    common_dir: Path
    """The git directory its worktrees share: the same for each of them."""
    git_dir: Path
    """Its own git directory: a linked worktree's is inside the common one."""
    is_main: bool
    """Whether it's the main worktree, not a linked one."""
    head: str | None
    """The branch checked out, or None for a detached HEAD."""
    trunk: str | None
    """The default branch, or None when it can't be told."""
    integration: Integration | None
    """None when its .workspace.toml sets none, which is its config error."""
    main_integration: Integration | None
    """The main worktree's, which is the same as integration in the main worktree."""
    worktrees: tuple[Worktree, ...]
    """Every worktree of the repository, this one included."""
    claude_working: bool
    """Whether a Claude Code session other than the one running this is busy here."""


@dataclass
class Directory:
    """A repository, or a directory of files that should probably be one."""

    path: Path
    is_repo: bool
    fetch_failed: bool = False
    """Whether fetching its remotes failed, so what's on them isn't known."""
    fetched: bool = False
    """Whether its remotes were fetched in this run, so what's on them is current."""
    git_failed: bool = False
    """Whether git couldn't read it, so the plugins found nothing."""
    found: dict[str, list[Problem]] = field(default_factory=dict)
    """What each plugin's check found, by the plugin's name."""
    place: Place | None = None
    """Where it stands among its repository's worktrees; None for a directory of files, or a
    repository git couldn't read."""
    config_error: str | None = None
    """What's wrong with its .workspace.toml's repo-tools settings, when something is."""
    trunk_update_failed: bool = False
    """Whether repo-fix failed to bring the trunk level with its upstream here."""
    trunk_stale: bool = False
    """Whether repo-fix failed to update the trunk in another of the repository's worktrees,
    so nothing here is caught up with it."""

    @property
    def problems(self) -> list[Problem]:
        """What the plugins found that needs attention, in their order, then whether fetch or
        git failed. A config error is the only problem shown, as nothing else can be judged
        until it's fixed."""
        if self.config_error:
            return [ConfigInvalid(self.config_error)]
        return [
            *(
                p
                for problems in self.found.values()
                for p in problems
                if not isinstance(p, Note | Badge)
            ),
            *([FetchFailed()] if self.fetch_failed else []),
            *([GitFailed()] if self.git_failed else []),
        ]

    @property
    def badges(self) -> dict[Slot, str]:
        """The icons saying what kind of repository it is, by their slot."""
        found = {
            p.slot: p.icon
            for problems in self.found.values()
            for p in problems
            if isinstance(p, Badge)
        }
        place = self.place
        if place and (icon := mode_icon(place.integration, place.is_main, place.main_integration)):
            found[Slot.MODE] = icon
        return found

    @property
    def notes(self) -> list[Problem]:
        """What the plugins found that needs no attention, in their order, then whether Claude
        is working here."""
        return [
            *(p for problems in self.found.values() for p in problems if isinstance(p, Note)),
            *([WORKING] if self.place and self.place.claude_working else []),
        ]


def find(directory: Path) -> list[Directory]:
    """The repositories below directory, and the directories of files in no repository, in name
    order.

    A directory holding only directories is a group, and is searched. Repositories are assumed
    not to be nested, so the search stops at each one and never walks into node_modules and the
    like. Hidden directories and symlinks are skipped.
    """
    found = []
    for child in sorted(directory.iterdir()):
        if child.name.startswith(".") or child.is_symlink() or not child.is_dir():
            continue
        if found_directory := classify(child):
            found.append(found_directory)
        else:
            found.extend(find(child))
    return found


def classify(directory: Path) -> Directory | None:
    """directory as a repository or a directory of files, or None for a group of directories."""
    if (directory / ".git").exists():
        return Directory(directory, is_repo=True)
    if any(f.is_file() and f.name != ".DS_Store" for f in directory.iterdir()):
        return Directory(directory, is_repo=False)
    return None


def survey(directories: list[Directory], plugins: list[Plugin], fetch_first: bool) -> None:
    """Runs every plugin's check of each directory, in parallel, after fetching every repository
    if asked: once for all of its worktrees, as they share their remotes."""
    repos = [f for f in directories if f.is_repo]
    with ThreadPoolExecutor(WORKERS) as pool:
        shared = list(pool.map(common_dir, [r.path for r in repos]))
        if fetch_first:
            first: dict[Path | None, Path] = {}
            for repo, common in zip(repos, shared, strict=True):
                first.setdefault(common if common else repo.path, repo.path)
            fetched = dict(zip(first, pool.map(fetch, first.values()), strict=True))
            for repo, common in zip(repos, shared, strict=True):
                repo.fetched = fetched[common if common else repo.path]
                repo.fetch_failed = not repo.fetched
        list(pool.map(lambda directory: locate(directory), repos))
        list(pool.map(lambda directory: check_all(directory, plugins), directories))
    for repo in repos:
        if repo.place is None:
            repo.found = {}
            repo.git_failed = True


def locate(directory: Directory) -> None:
    """Sets where the repository's directory stands among its worktrees, and its config error if it
    has one; leaves its place None when git can't read it."""
    directory.place, directory.config_error = None, None
    path = directory.path
    try:
        common = Path(git(path, "rev-parse", "--path-format=absolute", "--git-common-dir"))
        git_dir = Path(git(path, "rev-parse", "--absolute-git-dir"))
        head = git(path, "symbolic-ref", "-q", "--short", "HEAD", check=False) or None
        worktrees = parse_worktrees(git(path, "worktree", "list", "--porcelain"))
    except subprocess.CalledProcessError:
        return
    mode = workspace_integration(path)
    if isinstance(mode, Invalid):
        directory.config_error, mode = mode.message, None
    elif mode is None:
        directory.config_error = NO_MODE
    is_main = git_dir == common
    main_mode = mode
    if not is_main and worktrees:
        found = workspace_integration(worktrees[0].path)
        main_mode = found if isinstance(found, Integration) else None
    directory.place = Place(
        common_dir=common,
        git_dir=git_dir,
        is_main=is_main,
        head=head,
        trunk=default_branch(path, ask_remote=False),
        integration=mode,
        main_integration=main_mode,
        worktrees=tuple(worktrees),
        claude_working=agents.working(agents.sessions(git_dir), agents.own_session()),
    )


def workspace_integration(directory: Path) -> Integration | Invalid | None:
    """The integration mode the directory's .workspace.toml sets, None when it sets none, or
    what's wrong with it."""
    workspace = directory / WORKSPACE
    try:
        settings = tomllib.loads(workspace.read_text())
    except FileNotFoundError:
        return None
    except (OSError, tomllib.TOMLDecodeError) as error:
        return Invalid(f"{WORKSPACE}: {error}")
    table = settings.get(WORKSPACE_TABLE, {})
    if not isinstance(table, dict):
        return Invalid(f"{WORKSPACE}: {WORKSPACE_TABLE} must be a table")
    return integration_in(table, f"{WORKSPACE}: {WORKSPACE_TABLE}.integration")


def parse_worktrees(porcelain: str) -> list[Worktree]:
    """The worktrees `git worktree list --porcelain` lists, the main one first."""
    worktrees = []
    for block in porcelain.strip().split("\n\n"):
        lines = block.splitlines()
        if not lines or not lines[0].startswith("worktree "):
            continue
        attributes = dict(line.partition(" ")[::2] for line in lines)
        branch = attributes.get("branch", "").removeprefix("refs/heads/") or None
        worktrees.append(Worktree(Path(attributes["worktree"]), branch, "prunable" in attributes))
    return worktrees


def common_dir(repo: Path) -> Path | None:
    """The git directory the repository's worktrees share, or None when git can't read it."""
    try:
        return Path(git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    except subprocess.CalledProcessError:
        return None


def check_all(directory: Directory, plugins: list[Plugin]) -> None:
    """Sets what each plugin finds in the directory, in the plugins' order."""
    directory.found = {}
    directory.git_failed = False
    for plugin in plugins:
        if not check(directory, plugin):
            return


def check(directory: Directory, plugin: Plugin) -> bool:
    """Sets what the plugin finds in the directory. False if git couldn't read it, which leaves
    the directory with no problem found but that."""
    if not (directory.is_repo or plugin.checks_directories):
        return True
    try:
        directory.found[plugin.name] = plugin.check(directory)
    except subprocess.CalledProcessError:
        directory.found = {}
        directory.git_failed = True
        return False
    return True


def fetch(repo: Path) -> bool:
    """Fetch all of the repository's remotes. False if that failed or needed a password."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "fetch", "-q", "--all"],
            capture_output=True,
            env=batch_env(),
            timeout=FETCH_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return False
    return result.returncode == 0
