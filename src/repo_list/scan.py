"""Finding the repositories under a folder, and what the plugins find in each that needs
attention.

Shared by repo-list, which reports the problems, and repo-fix, which fixes them.
"""

import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from repo_list.git import batch_env
from repo_list.plugin import Note, Plugin, Problem

WORKERS = 8
FETCH_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class FetchFailed:
    def describe(self) -> str:
        return "📡 fetch failed"


@dataclass(frozen=True)
class GitFailed:
    """git couldn't read the repository."""

    def describe(self) -> str:
        return "💥 git failed"


@dataclass
class Folder:
    """A repository, or a folder of files that should probably be one."""

    path: Path
    is_repo: bool
    fetch_failed: bool = False
    """Whether fetching its remotes failed, so what's on them isn't known."""
    git_failed: bool = False
    """Whether git couldn't read it, so the plugins found nothing."""
    found: dict[str, list[Problem]] = field(default_factory=dict)
    """What each plugin's check found, by the plugin's name."""

    @property
    def problems(self) -> list[Problem]:
        """What the plugins found that needs attention, in their order, then whether fetch or
        git failed."""
        return [
            *(p for problems in self.found.values() for p in problems if not isinstance(p, Note)),
            *([FetchFailed()] if self.fetch_failed else []),
            *([GitFailed()] if self.git_failed else []),
        ]

    @property
    def notes(self) -> list[Problem]:
        """What the plugins found that needs no attention, in their order."""
        return [p for problems in self.found.values() for p in problems if isinstance(p, Note)]


def find(folder: Path) -> list[Folder]:
    """The repositories below folder, and the folders of files in no repository, in name order.

    A folder holding only folders is a group, and is searched. Repositories are assumed not to
    be nested, so the search stops at each one and never walks into node_modules and the like.
    Hidden folders and symlinks are skipped.
    """
    found = []
    for child in sorted(folder.iterdir()):
        if child.name.startswith(".") or child.is_symlink() or not child.is_dir():
            continue
        if found_folder := classify(child):
            found.append(found_folder)
        else:
            found.extend(find(child))
    return found


def classify(folder: Path) -> Folder | None:
    """folder as a repository or a folder of files, or None for a group of folders."""
    if (folder / ".git").exists():
        return Folder(folder, is_repo=True)
    if any(f.is_file() and f.name != ".DS_Store" for f in folder.iterdir()):
        return Folder(folder, is_repo=False)
    return None


def survey(folders: list[Folder], plugins: list[Plugin], fetch_first: bool) -> None:
    """Runs every plugin's check of each folder, in parallel, after fetching every repository
    if asked."""
    repos = [f for f in folders if f.is_repo]
    with ThreadPoolExecutor(WORKERS) as pool:
        fetched = list(pool.map(fetch, [r.path for r in repos])) if fetch_first else []
        for repo, ok in zip(repos, fetched or [True] * len(repos), strict=True):
            repo.fetch_failed = not ok
        list(pool.map(lambda folder: check_all(folder, plugins), folders))


def check_all(folder: Folder, plugins: list[Plugin]) -> None:
    """Sets what each plugin finds in the folder, in the plugins' order."""
    folder.found = {}
    folder.git_failed = False
    for plugin in plugins:
        if not check(folder, plugin):
            return


def check(folder: Folder, plugin: Plugin) -> bool:
    """Sets what the plugin finds in the folder. False if git couldn't read it, which leaves
    the folder with no problem found but that."""
    if not (folder.is_repo or plugin.checks_folders):
        return True
    try:
        folder.found[plugin.name] = plugin.check(folder)
    except subprocess.CalledProcessError:
        folder.found = {}
        folder.git_failed = True
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
