"""👻 Commits on a detached HEAD, reachable from no branch or remote. Left for you."""

from dataclasses import dataclass

from repo_list.git import git, run
from repo_list.plugin import Plugin, Problem, count
from repo_list.scan import Directory


@dataclass(frozen=True)
class DetachedCommits:
    commits: int

    def describe(self) -> str:
        return f"👻 {count(self.commits, 'commit')} on detached HEAD"


class Detached(Plugin):
    name = "detached"

    def check(self, directory: Directory) -> list[Problem]:
        if run(directory.path, "symbolic-ref", "--quiet", "HEAD").returncode == 0:
            return []
        commits = int(
            git(directory.path, "rev-list", "--count", "HEAD", "--not", "--branches", "--remotes")
        )
        return [DetachedCommits(commits)] if commits else []
