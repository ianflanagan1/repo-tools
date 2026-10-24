"""What a plugin is: a check of each directory repo-list finds, and, optionally, a fix for what it
finds, which repo-fix runs at the plugin's stage.

repo-list runs every plugin's check, in the order the plugins are given, and shows what each
finds in that order. repo-fix runs the fixes stage by stage, so that work is committed before it
is pushed, and pushed before other services are told about it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from repo_list.scan import Directory


class Stage(Enum):
    """When repo-fix runs a plugin's fix. The stages run in this order."""

    INIT = "init"
    """Make a directory of files a repository."""
    COMMIT = "commit"
    """Commit the work in the working tree."""
    BEFORE_PUSH = "before-push"
    """Change commits that are on no remote yet, which needs no force push."""
    PUBLISH = "publish"
    """Give the repository a remote."""
    SYNC = "sync"
    """Bring each branch level with its upstream."""
    AFTER_PUSH = "after-push"
    """Bring other services level with what was pushed."""


class Problem(Protocol):
    def describe(self) -> str:
        """The problem as repo-list shows it, marked by its emoji."""
        ...


@dataclass(frozen=True)
class Note:
    """A finding worth showing beside the directory that needs no attention, such as the branch
    checked out. A check's finding is one by subclassing this. repo-list shows notes in a column
    of their own, before the problems."""

    text: str
    quiet: bool = False
    """Whether it's dimmed, as the expected case."""

    def describe(self) -> str:
        return self.text


class Slot(Enum):
    """Where a badge goes in its column, in this order."""

    MODE = "mode"
    """The integration mode."""
    HOST = "host"
    """Where the remote repository is, such as GitHub, or that there's none."""
    VISIBILITY = "visibility"
    """Who can see the remote repository."""


@dataclass(frozen=True)
class Badge:
    """An icon saying what kind of repository a directory is, shown in a column of its own
    between the mark and the path, and explained in the README. Each icon is two columns wide,
    and from Unicode 11 or earlier, the widths VS Code's terminal knows."""

    slot: Slot
    icon: str

    def describe(self) -> str:
        return self.icon


class Log(Protocol):
    def __call__(self, ok: bool, line: str, *details: str) -> None:
        """Shows one thing a fix did, or failed to do, with any details quoted under it."""
        ...


class Plugin(Protocol):
    name: str
    """Unique among the plugins."""
    stage: Stage | None = None
    """When repo-fix runs the fix, or None for a plugin that only checks."""
    checks_directories: bool = False
    """Whether the check also sees directories that aren't repositories."""

    def check(self, directory: Directory) -> list[Problem]:
        """What in the directory needs attention.

        Raises CalledProcessError when git can't read the repository, which is then reported as
        that alone.
        """
        ...

    def fix(self, directory: Directory, problems: list[Problem], log: Log) -> bool:
        """Fixes what it can of problems, which its check has just found, logging what it did.
        False stops repo-fix's work on the directory there."""
        return True


def count(n: int, noun: str) -> str:
    """'1 file', '2 files'."""
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"
