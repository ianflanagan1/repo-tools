"""Badges for a repository's remote: its git host, such as 🐙 GitHub, or 🔌 none, or 💻 none
because its settings keep it on this computer only; and who can see it, 🌐 public or 🔒 private.
Every worktree shows them, though they share the remote. And 🧭 when origin isn't where the
worktree's .config/ianf-repo-tools.toml puts it, or isn't seen by who its visibility says, which
only a person can tell the right one of, so repo-fix leaves it.

The git host is told by the remote's URL. Who can see it is asked of the git host, so only when
the remotes were fetched in this run: repo-list with --fetch, and repo-fix. A git host or server
repo-tools has no adapter for, or one that can't say, leaves it blank. That there's no remote is
also a problem, the publish plugin's.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import assert_never, final

from git_default_branch import remote_to_ask

from repo_list import git_hosts
from repo_list.git import git
from repo_list.git_hosts import ORIGIN, GitHost, LocalOnly, Origin, Visibility, git_host_at
from repo_list.plugin import Badge, Plugin, Problem, Slot
from repo_list.remote_repos import RemoteRepo, Unknown, git_host_icon
from repo_list.scan import SETTINGS, Directory

NO_REMOTE = "🔌"
LOCAL_ONLY = "💻"


def icon(visibility: Visibility) -> str:
    match visibility:
        case Visibility.PUBLIC:
            return "🌐"
        case Visibility.PRIVATE:
            return "🔒"
        case _:
            assert_never(visibility)


@final
@dataclass(frozen=True)
class NoOrigin:
    """There are remotes, but no origin, which the settings put on a git host."""

    expected: GitHost

    def describe(self) -> str:
        return (
            f"🧭 no {ORIGIN} remote, though {SETTINGS} puts it on {git_hosts.title(self.expected)}"
        )


@final
@dataclass(frozen=True)
class OriginElsewhere:
    """Origin isn't on the git host the settings put it on."""

    expected: GitHost
    actual: GitHost | None
    """The git host origin is on, or None for another git host or server, or a path."""

    def describe(self) -> str:
        on = "another git host or server" if self.actual is None else git_hosts.title(self.actual)
        expected = git_hosts.title(self.expected)
        return f"🧭 {ORIGIN} is on {on}, though {SETTINGS} puts it on {expected}"


@final
@dataclass(frozen=True)
class RemoteOfLocalOnly:
    """There's a remote, though the settings keep the repository on this computer only."""

    def describe(self) -> str:
        return f"🧭 has a remote, though {SETTINGS} keeps it local"


@final
@dataclass(frozen=True)
class SeenOtherwise:
    """Origin's git host says it's seen by others than the settings' visibility says."""

    expected: Visibility
    actual: Visibility

    def describe(self) -> str:
        return f"🧭 {ORIGIN} is {self.actual}, though {SETTINGS} makes it {self.expected}"


type Mismatch = NoOrigin | OriginElsewhere | RemoteOfLocalOnly


def mismatch(expected: Origin | None, remotes: list[str], origin_url: str) -> Mismatch | None:
    """How the remotes differ from where the settings put origin, or None when they don't, or
    when the settings name nothing or there's no remote, which is reported as 🔌 instead."""
    if expected is None or not remotes:
        return None
    match expected:
        case LocalOnly():
            return RemoteOfLocalOnly()
        case GitHost():
            if ORIGIN not in remotes:
                return NoOrigin(expected)
            actual = git_host_at(origin_url)
            return None if actual is expected else OriginElsewhere(expected, actual)
        case _:
            assert_never(expected)


class Remote(Plugin):
    name = "remote"

    def __init__(self, remote_repo_at: Callable[[str], RemoteRepo | None]) -> None:
        self.remote_repo_at = remote_repo_at

    def check(self, directory: Directory) -> list[Problem]:
        place = directory.place
        if place is None:
            return []
        repo = directory.path
        remotes = git(repo, "remote").splitlines()
        if not remotes:
            local_only = isinstance(place.origin, LocalOnly)
            return [Badge(Slot.GIT_HOST, LOCAL_ONLY if local_only else NO_REMOTE)]
        origin_url = git(repo, "config", f"remote.{ORIGIN}.url", check=False)
        elsewhere = mismatch(place.origin, remotes, origin_url)
        found: list[Problem] = [elsewhere] if elsewhere else []
        remote = remote_to_ask(remotes)
        if remote is None:
            return found
        url = git(repo, "config", f"remote.{remote}.url", check=False)
        found.append(Badge(Slot.GIT_HOST, git_host_icon(url)))
        remote_repo = self.remote_repo_at(url) if directory.fetched else None
        if remote_repo is None:
            return found
        match remote_repo.visibility():
            case Unknown():
                return found
            case Visibility() as visibility:
                expected = place.visibility if remote == ORIGIN else None
                seen = (
                    [SeenOtherwise(expected, visibility)]
                    if expected is not None and expected is not visibility
                    else []
                )
                return [*seen, *found, Badge(Slot.VISIBILITY, icon(visibility))]
            case _ as answer:
                assert_never(answer)
