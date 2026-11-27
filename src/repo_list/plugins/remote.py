"""Badges for a repository's remote: its git host, such as 🐙 GitHub, or 🔌 none, or 💻 none
because its settings keep it on this computer only; and who can see it, 🌐 public or 🔒 private.
Every worktree shows them, though they share the remote. And 🧭 when origin isn't where the
worktree's .config/ianf-repo-tools.toml puts it, or isn't seen by who its visibility says, which
only a person can tell the right one of, so repo-fix leaves it.

The git host is told by the remote's URL. Origin on a git host repo-tools has an adapter for
must have both its git host and its visibility in the settings, which say who can see it on every
run, and 🔧 when they don't; repo-fix asks for them. The git host is asked who can see it only when
the remotes were fetched in this run, repo-list with --fetch and repo-fix, to check the settings,
and a git host that can't say is then reported, so the check never lapses unseen. For any other
remote, who can see it is what the git host says, when asked; a git host or server repo-tools has
no adapter for, or one that can't say, leaves it blank. That there's no remote is also a
problem, the publish plugin's.
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


@final
@dataclass(frozen=True)
class OriginUnsaid:
    """Origin is on a git host, but the settings don't say which, or who can see it there, as
    every repository published must."""

    git_host: GitHost
    """The git host origin is on, by its URL."""
    unset: tuple[str, ...]
    """The settings of [remotes.origin] that are missing: git-host, visibility, or both."""
    seen: Visibility | None
    """Who the git host says can see origin, or None when it wasn't asked or couldn't say."""

    def describe(self) -> str:
        settings = " or ".join(f"remotes.{ORIGIN}.{setting}" for setting in self.unset)
        return f"🔧 {SETTINGS} doesn't set {settings}"


@final
@dataclass(frozen=True)
class VisibilityUnchecked:
    """Origin's git host couldn't say who can see it, so the settings' visibility wasn't
    checked."""

    git_host: GitHost
    reason: str

    def describe(self) -> str:
        on = git_hosts.title(self.git_host)
        return f"🧭 {on} couldn't say who can see {ORIGIN}: {self.reason}"


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
        seen = remote_repo.visibility() if remote_repo else None
        if remote != ORIGIN:
            return [*found, *_shown(seen)]
        return [*about_origin(place.origin, place.visibility, git_host_at(url), seen), *found]


def about_origin(
    origin: Origin | None,
    expected: Visibility | None,
    on: GitHost | None,
    seen: Visibility | Unknown | None,
) -> list[Problem]:
    """What to show of who can see origin, given where the settings put it and who they say can
    see it, the git host its URL is on, None for one there's no adapter for, and what that git
    host said, None when it wasn't asked: the settings' visibility, and how the git host differs
    from them, or that they're missing; without them, or when they put origin elsewhere, which
    is reported already, what the git host said."""
    if on is None or isinstance(origin, LocalOnly) or origin not in (None, on):
        return _shown(seen)
    named = (("git-host", origin), ("visibility", expected))
    unset = tuple(setting for setting, value in named if value is None)
    unsaid: list[Problem] = (
        [OriginUnsaid(on, unset, seen if isinstance(seen, Visibility) else None)] if unset else []
    )
    if expected is None:
        return [*unsaid, *_shown(seen)]
    drift: list[Problem]
    match seen:
        case None:
            drift = []
        case Unknown():
            drift = [VisibilityUnchecked(on, seen.reason)]
        case Visibility():
            drift = [] if seen is expected else [SeenOtherwise(expected, seen)]
        case _:
            assert_never(seen)
    return [*unsaid, *drift, Badge(Slot.VISIBILITY, icon(expected))]


def _shown(seen: Visibility | Unknown | None) -> list[Problem]:
    """The badge of who the git host says can see the remote, when it said."""
    return [Badge(Slot.VISIBILITY, icon(seen))] if isinstance(seen, Visibility) else []
