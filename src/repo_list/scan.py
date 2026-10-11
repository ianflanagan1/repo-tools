"""Finding the repositories under a folder, and what in each needs attention.

Shared by repo-list, which reports the problems, and repo-fix, which fixes them.
"""

import json
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from cli_kit.errors import Failure

from repo_tools.packagist import api as packagist

FETCH_WORKERS = 8
FETCH_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class Uncommitted:
    """Files changed, staged or untracked."""

    files: int


@dataclass(frozen=True)
class Unpushed:
    """Commits on a local branch that are on no remote."""

    branch: str
    commits: int


@dataclass(frozen=True)
class Behind:
    """Commits on the branch's upstream that it lacks, as of the last fetch."""

    branch: str
    commits: int


@dataclass(frozen=True)
class Detached:
    """Commits on a detached HEAD, reachable from no branch or remote."""

    commits: int


@dataclass(frozen=True)
class Stashed:
    stashes: int


@dataclass(frozen=True)
class NoRemote:
    pass


@dataclass(frozen=True)
class NotARepo:
    """A folder of files in no repository."""


@dataclass(frozen=True)
class FetchFailed:
    pass


@dataclass(frozen=True)
class GitFailed:
    """git couldn't read the repository."""


@dataclass(frozen=True)
class NotOnPackagist:
    pass


@dataclass(frozen=True)
class PackagistBehind:
    """Version tags, and branches at a commit, on origin that Packagist doesn't offer yet."""

    lacking: tuple[str, ...]


@dataclass(frozen=True)
class PackagistFailed:
    """Packagist, or the ls-remote of origin to compare it with, couldn't be read."""


type Problem = (
    Uncommitted
    | Unpushed
    | Behind
    | Detached
    | Stashed
    | NoRemote
    | NotARepo
    | FetchFailed
    | GitFailed
    | NotOnPackagist
    | PackagistBehind
    | PackagistFailed
)


@dataclass
class Folder:
    """A repository, or a folder of files that should probably be one."""

    path: Path
    is_repo: bool
    problems: list[Problem] = field(default_factory=list)


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


def survey(folders: list[Folder], fetch_first: bool, packagist_vendor: str | None = None) -> None:
    """Sets each folder's problems, after fetching every repository in parallel if asked.

    With packagist_vendor, each package of that vendor's is also checked against Packagist, in
    parallel, unless its fetch failed.
    """
    repos = [f for f in folders if f.is_repo]
    fetched = [True] * len(repos)
    if fetch_first:
        with ThreadPoolExecutor(FETCH_WORKERS) as pool:
            fetched = list(pool.map(fetch, [r.path for r in repos]))
    for repo, ok in zip(repos, fetched, strict=True):
        repo.problems = [] if ok else [FetchFailed()]
    for folder in folders:
        if not folder.is_repo:
            folder.problems = [NotARepo()]
            continue
        try:
            folder.problems[:0] = check(folder.path)
        except subprocess.CalledProcessError:
            folder.problems.append(GitFailed())
    if packagist_vendor:
        readable = [r for r in repos if not {FetchFailed(), GitFailed()} & set(r.problems)]
        with ThreadPoolExecutor(FETCH_WORKERS) as pool:
            checked = pool.map(
                lambda path: check_packagist(path, packagist_vendor), [r.path for r in readable]
            )
            for repo, problems in zip(readable, checked, strict=True):
                repo.problems.extend(problems)


def git(repo: Path, *args: str) -> str:
    """Run a git command in repo and return its output. Raises CalledProcessError on failure."""
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout


def check(repo: Path) -> list[Problem]:
    """What in the repository needs attention."""
    problems: list[Problem] = []

    has_remote = bool(git(repo, "remote").strip())
    if not has_remote:
        problems.append(NoRemote())

    uncommitted = len(git(repo, "status", "--porcelain").splitlines())
    if uncommitted:
        problems.append(Uncommitted(uncommitted))

    branches = git(
        repo, "for-each-ref", "--format=%(refname:short)\t%(upstream:track,nobracket)", "refs/heads"
    )
    for line in branches.splitlines():
        branch, _, track = line.partition("\t")
        # Count commits on no remote, rather than ahead of the upstream, so that a branch
        # without an upstream is still checked. With no remote, "no remote" already says it all.
        if has_remote:
            unpushed = int(
                git(repo, "rev-list", "--count", f"refs/heads/{branch}", "--not", "--remotes")
            )
            if unpushed:
                problems.append(Unpushed(branch, unpushed))
        # track is like "ahead 1, behind 2", as of the last fetch.
        if behind := re.search(r"behind (\d+)", track):
            problems.append(Behind(branch, int(behind[1])))

    on_branch = subprocess.run(
        ["git", "-C", str(repo), "symbolic-ref", "-q", "HEAD"], capture_output=True
    )
    if on_branch.returncode != 0:
        detached = int(git(repo, "rev-list", "--count", "HEAD", "--not", "--branches", "--remotes"))
        if detached:
            problems.append(Detached(detached))

    stashes = len(git(repo, "stash", "list").splitlines())
    if stashes:
        problems.append(Stashed(stashes))

    return problems


def check_packagist(repo: Path, vendor: str) -> list[Problem]:
    """What Packagist lacks of the repository, if it is a package of vendor's with an origin.
    Reads the network."""
    package = package_name(repo, vendor)
    if package is None or "origin" not in git(repo, "remote").split():
        return []
    try:
        lacking = packagist.lacks(package, repo)
    except Failure:
        return [PackagistFailed()]
    if lacking is None:
        return [NotOnPackagist()]
    return [PackagistBehind(tuple(lacking))] if lacking else []


def package_name(repo: Path, vendor: str) -> str | None:
    """The name in the repository's composer.json, if it is a package of vendor's."""
    try:
        name = json.loads((repo / "composer.json").read_text()).get("name")
    except (OSError, ValueError, AttributeError):
        return None
    if isinstance(name, str) and name.startswith(f"{vendor}/"):
        return name
    return None


def batch_env() -> dict[str, str]:
    """The environment for a git command that talks to a remote: it fails rather than stopping
    to ask for a password."""
    return os.environ | {
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_SSH_COMMAND": os.environ.get("GIT_SSH_COMMAND", "ssh") + " -o BatchMode=yes",
    }


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
