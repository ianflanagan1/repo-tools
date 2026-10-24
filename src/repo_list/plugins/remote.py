"""Badges in the main worktree for its remote: its host, such as 🐙 GitHub, or 🔌 none; and who
can see it, 🌐 public or 🔒 private. Linked worktrees share the remote, so they leave both blank.

The host is told by the remote's URL. Who can see it is asked of the host, so only when the
remotes were fetched in this run: repo-list with --fetch, and repo-fix. A host repo-tools has no
adapter for, or one that can't say, leaves it blank. That there's no remote is also a problem,
the github plugin's.
"""

from collections.abc import Callable
from typing import assert_never

from git_default_branch import remote_to_ask

from repo_list.git import git
from repo_list.hosts import Host, Unknown, Visibility, host_icon
from repo_list.plugin import Badge, Plugin, Problem, Slot
from repo_list.scan import Directory

NO_REMOTE = "🔌"


def icon(visibility: Visibility) -> str:
    match visibility:
        case Visibility.PUBLIC:
            return "🌐"
        case Visibility.PRIVATE:
            return "🔒"
        case _:
            assert_never(visibility)


class Remote(Plugin):
    name = "remote"

    def __init__(self, hosts: Callable[[str], Host | None]) -> None:
        self.hosts = hosts

    def check(self, directory: Directory) -> list[Problem]:
        place = directory.place
        if place is None or not place.is_main:
            return []
        repo = directory.path
        remotes = git(repo, "remote").splitlines()
        if not remotes:
            return [Badge(Slot.HOST, NO_REMOTE)]
        remote = remote_to_ask(remotes)
        if remote is None:
            return []
        url = git(repo, "config", f"remote.{remote}.url", check=False)
        found = [Badge(Slot.HOST, host_icon(url))]
        host = self.hosts(url) if directory.fetched else None
        if host is None:
            return found
        match host.visibility():
            case Unknown():
                return found
            case Visibility() as visibility:
                return [*found, Badge(Slot.VISIBILITY, icon(visibility))]
            case _ as answer:
                assert_never(answer)
