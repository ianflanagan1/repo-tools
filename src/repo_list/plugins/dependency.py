"""Badges for each kind of dependency a repository is, such as 🐘 Composer, read from the
manifests in its working tree, and for Python and Go from what the others pin; none for a
repository that is no dependency. Each worktree shows its own, as its branch may make it a
different kind.

Whose dependency it is doesn't matter here: the Packagist and npm checks judge that.
"""

from collections.abc import Set
from pathlib import Path

from repo_list.plugin import Badge, Plugin, Problem, Slot
from repo_list.scan import Directory
from repo_tools import dependencies
from repo_tools.dependencies import Name


class Dependency(Plugin):
    name = "dependency"

    def __init__(self, pinned: Set[Name], offering: Set[Path]) -> None:
        self.pinned = pinned
        """Every name the directories found pin."""
        self.offering = offering
        """Every directory found whose flake has an output for other flakes."""

    def check(self, directory: Directory) -> list[Problem]:
        found = dependencies.discover(directory.path, self.pinned, self.offering)
        return [Badge(Slot.DEPENDENCY, dependencies.icon(d)) for d in found]
