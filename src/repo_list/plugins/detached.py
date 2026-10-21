"""👻 Commits on a detached HEAD, reachable from no branch or remote. Left for you."""

from dataclasses import dataclass

from repo_list.git import git, run
from repo_list.plugin import Plugin, Problem, count
from repo_list.scan import Folder


@dataclass(frozen=True)
class DetachedCommits:
    commits: int

    def describe(self) -> str:
        return f"👻 {count(self.commits, 'commit')} on detached HEAD"


class Detached(Plugin):
    name = "detached"

    def check(self, folder: Folder) -> list[Problem]:
        if run(folder.path, "symbolic-ref", "-q", "HEAD").returncode == 0:
            return []
        commits = int(
            git(folder.path, "rev-list", "--count", "HEAD", "--not", "--branches", "--remotes")
        )
        return [DetachedCommits(commits)] if commits else []
