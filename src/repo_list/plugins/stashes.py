"""📦 Stashes. Left for you."""

from dataclasses import dataclass

from repo_list.git import git
from repo_list.plugin import Plugin, Problem, count
from repo_list.scan import Folder


@dataclass(frozen=True)
class Stashed:
    stashes: int

    def describe(self) -> str:
        return f"📦 {count(self.stashes, 'stash')}"


class Stashes(Plugin):
    name = "stashes"

    def check(self, folder: Folder) -> list[Problem]:
        stashes = len(git(folder.path, "stash", "list").splitlines())
        return [Stashed(stashes)] if stashes else []
