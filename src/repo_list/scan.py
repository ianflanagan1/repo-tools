"""Finding the repositories under a directory, and what the plugins find in each that needs
attention.

Shared by repo-list, which reports the problems, and repo-fix, which fixes them.
"""

import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import assert_never, final

import repo_settings
from git_default_branch import default_branch
from repo_settings import Missing, Source, Text, Unlocatable

from repo_list import agents
from repo_list.config import Invalid, Version, integration_in, skip_fix_in
from repo_list.git import batch_env, git
from repo_list.integration import Integration, Worktree, integration_icon
from repo_list.plugin import Badge, Note, Plugin, Problem, Slot

WORKERS = 8
FETCH_TIMEOUT_SECONDS = 60
PURPOSE = "repo-tools"
SETTINGS = repo_settings.location(PURPOSE)
"""Where a repository keeps repo-tools' settings, which its team shares."""
NO_INTEGRATION = f"Set `integration` in {SETTINGS}"


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
    """The repository's .config/ianf-repo-tools.toml has a setting that can't be used."""

    message: str

    def describe(self) -> str:
        return f"🔧 {self.message}"


WORKING = Note("🤖 Claude working")
"""A Claude Code session is busy in the directory, so repo-fix leaves it alone."""
SKIPPED = Note("💤 repo-fix skips")
"""The directory's .config/ianf-repo-tools.toml sets skip-fix, so repo-fix leaves it alone."""


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
    """The trunk, or None when it can't be told."""
    integration: Integration | None
    """None when its .config/ianf-repo-tools.toml sets none, which is its config error."""
    worktrees: tuple[Worktree, ...]
    """Every worktree of the repository, this one included."""
    claude_working: bool
    """Whether a Claude Code session other than the one running this is busy here."""
    skip_fix: bool
    """Whether its .config/ianf-repo-tools.toml asks repo-fix to leave it alone."""


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
    """What's wrong with its .config/ianf-repo-tools.toml, when something is."""
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
        """The icons saying what kind of repository it is, by their slot, side by side where a
        slot has several."""
        found: dict[Slot, str] = {}
        for problems in self.found.values():
            for p in problems:
                if isinstance(p, Badge):
                    found[p.slot] = found.get(p.slot, "") + p.icon
        place = self.place
        if place:
            found[Slot.INTEGRATION] = integration_icon(place.integration)
        return found

    @property
    def notes(self) -> list[Problem]:
        """What the plugins found that needs no attention, in their order, then whether Claude
        is working here, then whether repo-fix skips it."""
        return [
            *(p for problems in self.found.values() for p in problems if isinstance(p, Note)),
            *([WORKING] if self.place and self.place.claude_working else []),
            *([SKIPPED] if self.place and self.place.skip_fix else []),
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
        head = git(path, "symbolic-ref", "--quiet", "--short", "HEAD", check=False) or None
        worktrees = parse_worktrees(git(path, "worktree", "list", "--porcelain"))
    except subprocess.CalledProcessError:
        return
    own = settings(Source.LOCAL_THIS_WORKTREE, path)
    integration = own if isinstance(own, Invalid) else own.integration
    skip_fix = own if isinstance(own, Invalid) else own.skip_fix
    if isinstance(integration, Invalid):
        directory.config_error, integration = integration.message, None
    elif integration is None:
        directory.config_error = NO_INTEGRATION
    elif isinstance(skip_fix, Invalid):
        directory.config_error = skip_fix.message
    is_main = git_dir == common
    directory.place = Place(
        common_dir=common,
        git_dir=git_dir,
        is_main=is_main,
        head=head,
        trunk=default_branch(path, ask_remote=False),
        integration=integration,
        worktrees=tuple(worktrees),
        claude_working=agents.working(agents.sessions(git_dir), agents.own_session()),
        skip_fix=skip_fix is True,
    )


@final
@dataclass(frozen=True)
class Settings:
    """What a copy of .config/ianf-repo-tools.toml sets, each setting or what's wrong with it."""

    integration: Integration | Invalid | None
    """None when it sets none."""
    skip_fix: bool | Invalid


def settings(source: Source, directory: Path) -> Settings | Invalid:
    """What the source's copy of .config/ianf-repo-tools.toml sets, nothing when there's no such
    file, or what's wrong with the file."""
    found = repo_settings.fetch(source, directory, PURPOSE)
    match found:
        case Text():
            pass
        case Missing():
            return Settings(integration=None, skip_fix=False)
        case Unlocatable():
            return Invalid(" ".join((found.message, *found.details)))
        case _:
            assert_never(found)
    read = repo_settings.loads(found.text, SETTINGS, Version)
    if isinstance(read, repo_settings.Invalid):
        return Invalid(" ".join((read.message, *read.details)))
    match read.version:
        case Version.V1:
            return Settings(
                integration=integration_in(read.table, f"{SETTINGS}: integration"),
                skip_fix=skip_fix_in(read.table, f"{SETTINGS}: skip-fix"),
            )
        case _:
            assert_never(read.version)


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
            ["git", "-C", str(repo), "fetch", "--quiet", "--all"],
            capture_output=True,
            env=batch_env(),
            timeout=FETCH_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return False
    return result.returncode == 0
