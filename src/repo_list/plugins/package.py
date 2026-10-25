"""Badges for each kind of package a repository is, such as 🐘 Composer, read from the manifests
in its working tree, and for Python from what the others pin; none for a repository that is no
package. Each worktree shows its own, as its branch may make it a different kind.

Whose package it is doesn't matter here: the Packagist and npm checks judge that.
"""

from collections.abc import Set

from repo_list.plugin import Badge, Plugin, Problem, Slot
from repo_list.scan import Directory
from repo_tools import packages
from repo_tools.packages import Name


class Package(Plugin):
    name = "package"

    def __init__(self, pinned: Set[Name]) -> None:
        self.pinned = pinned
        """Every name the directories found pin."""

    def check(self, directory: Directory) -> list[Problem]:
        found = packages.discover(directory.path, self.pinned)
        return [Badge(Slot.PACKAGE, packages.icon(package)) for package in found]
