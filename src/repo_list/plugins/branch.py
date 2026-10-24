"""Where HEAD is: the branch checked out, or the commit a detached HEAD is at, as @3f2a1c9.
Shown, not fixed, and never needing attention by itself: a detached HEAD's own commits are the
detached plugin's to report.

The default branch is dimmed, as the expected case, so that any other stands out. It's the one
git-default-branch tells, as everywhere in repo-tools.
"""

from dataclasses import dataclass

from repo_list.git import git
from repo_list.plugin import Note, Plugin, Problem
from repo_list.scan import Directory


@dataclass(frozen=True)
class Head:
    branch: str | None
    """The branch checked out, or None for a detached HEAD."""
    commit: str
    """HEAD's abbreviated commit, or "" before the first commit."""
    default: str | None
    """The default branch, or None when it isn't known."""


def assess(head: Head) -> list[Problem]:
    """How HEAD is shown."""
    if head.branch is None:
        return [Note(f"@{head.commit}", quiet=False)]
    return [Note(head.branch, quiet=head.branch == head.default)]


class Branch(Plugin):
    name = "branch"

    def check(self, directory: Directory) -> list[Problem]:
        repo = directory.path
        branch = git(repo, "symbolic-ref", "-q", "--short", "HEAD", check=False) or None
        commit = git(repo, "rev-parse", "-q", "--short", "--verify", "HEAD", check=False)
        trunk = directory.place.trunk if directory.place else None
        return assess(Head(branch, commit, trunk))
