"""🔗 A project whose lock file holds a package of yours, from another repository here, at less than
its latest: for a package released by version tag, its highest version tag; for a Python package
pinned from a git branch, the trunk as pushed.

It only reports, and only on the trunk with direct integration, where repo-fix's 📌 upgrades every
lock file in full, after releasing and publishing what the project pins. So in repo-fix's report it
is what that upgrade couldn't reach, such as a new major version the project's constraint
excludes, which needs its manifest changed.
"""

from collections.abc import Mapping, Set
from dataclasses import dataclass
from pathlib import Path

from git_default_branch import default_branch

from repo_list import ecosystems
from repo_list.git import git
from repo_list.plugin import Plugin, Problem
from repo_list.plugins import lock
from repo_list.scan import Directory
from repo_tools import dependencies, versions
from repo_tools.dependencies import Ecosystem, Name


@dataclass(frozen=True)
class Upgrade:
    name: str
    locked: str
    latest: str

    def describe(self) -> str:
        return f"{self.name} {_shown(self.locked)} -> {_shown(self.latest)}"


@dataclass(frozen=True)
class Behind:
    ecosystem: Ecosystem
    upgrades: tuple[Upgrade, ...]

    def describe(self) -> str:
        names = ", ".join(u.name for u in self.upgrades)
        return f"🔗 {ecosystems.lock_file(self.ecosystem)} behind on {names}"


class Dependants(Plugin):
    name = "dependants"

    def __init__(self, chosen: Set[Ecosystem], providers: Mapping[Name, Path]) -> None:
        self.chosen = chosen
        self.providers = providers
        """The repository each package of yours here comes from, by its name."""

    def check(self, directory: Directory) -> list[Problem]:
        """Each lock file, of the ecosystems chosen, that holds a package of yours at less than
        its latest, when the trunk is checked out here with direct integration."""
        repo = directory.path
        if not lock.on_direct_trunk(directory):
            return []
        own = dependencies.names(repo)
        found: list[Problem] = []
        for ecosystem in (e for e in Ecosystem if e in self.chosen):
            path = repo / ecosystems.lock_file(ecosystem)
            if not path.is_file():
                continue
            upgrades = []
            for name, at in sorted(ecosystems.locked(ecosystem, path.read_text()).items()):
                provider = self.providers.get(Name(ecosystem, name))
                if provider is None or Name(ecosystem, name) in own:
                    continue
                latest = _latest(ecosystem, provider)
                if latest and ecosystems.is_behind(ecosystem, at, latest):
                    upgrades.append(Upgrade(name, at, latest))
            if upgrades:
                found.append(Behind(ecosystem, tuple(upgrades)))
        return found


def _latest(ecosystem: Ecosystem, provider: Path) -> str | None:
    """The latest of the package in the provider: its highest version tag, or for an ecosystem
    that isn't released by tag, the commit its trunk's upstream is at."""
    if ecosystems.releases_by_tag(ecosystem):
        tags = [t for t in git(provider, "tag", check=False).split() if versions.is_version(t)]
        return max(tags, key=versions.key, default=None)
    trunk = default_branch(provider, ask_remote=False)
    if trunk is None:
        return None
    return git(provider, "rev-parse", "--verify", "--quiet", f"{trunk}@{{upstream}}", check=False)


def _shown(locked: str) -> str:
    """A version as it is, and a commit abbreviated."""
    return locked if versions.is_version(locked) else locked[:7]
