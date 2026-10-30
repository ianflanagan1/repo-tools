"""🔖 A package of yours with commits since its latest version, released as the next patch version
with `github release` or `bitbucket release`, so that the registries, and the projects that pin
it, get them.

A package never released is released too, as v0.0.1, the first patch version; a minor or major
version is yours to release, with `github release <dir> minor`. Only for an ecosystem whose
packages are released by version tag, not Python's, whose dependants pin a commit. Only the trunk
is released, with direct integration, and after it's pushed, but before its registry is told, so
that a package new to npm has a version tag to publish. Commits since a release that change lock
files alone aren't released: see ecosystems.needs_release.
"""

import subprocess
import sys
from collections.abc import Set
from dataclasses import dataclass
from pathlib import Path

from repo_list import ecosystems
from repo_list.config import Config
from repo_list.git import git
from repo_list.plugin import Log, Plugin, Problem, Stage, count
from repo_list.plugins import github
from repo_list.plugins.lock import on_direct_trunk
from repo_list.scan import Directory
from repo_tools import versions
from repo_tools.packages import Ecosystem, Name

BITBUCKET = str(Path(sys.prefix) / "bin" / "bitbucket")
LEVEL = "patch"


@dataclass(frozen=True)
class Unreleased:
    since: str | None
    """The latest version tag, or None for a package never released."""
    commits: int

    def describe(self) -> str:
        if self.since is None:
            return "🔖 never released"
        return f"🔖 {count(self.commits, 'commit')} since {self.since}"


class Release(Plugin):
    name = "release"
    stage = Stage.RELEASE

    def __init__(self, chosen: Set[Ecosystem], settings: Config, pinned: Set[Name]) -> None:
        self.chosen = chosen
        self.settings = settings
        self.pinned = pinned
        """Every name the directories found pin, which makes a Python project a package."""

    def check(self, directory: Directory) -> list[Problem]:
        """The commits since the latest version worth releasing, or every commit of a package
        never released, when the trunk of a package of yours released by version tag is checked
        out here with direct integration."""
        repo = directory.path
        if not on_direct_trunk(directory):
            return []
        names = ecosystems.yours(repo, self.chosen, self.settings, self.pinned)
        if not any(ecosystems.releases_by_tag(name.ecosystem) for name in names):
            return []
        tags = [t for t in git(repo, "tag", "--merged", "HEAD").split() if versions.is_version(t)]
        if not tags:
            return [Unreleased(None, int(git(repo, "rev-list", "--count", "HEAD")))]
        since = max(tags, key=versions.key)
        changed = git(repo, "diff", "--name-only", since, "HEAD").splitlines()
        if not ecosystems.needs_release(changed):
            return []
        return [Unreleased(since, int(git(repo, "rev-list", "--count", f"{since}..HEAD")))]

    def fix(self, directory: Directory, problems: list[Problem], log: Log) -> bool:
        """Releases HEAD as the next patch version on origin's host. Says whether it worked."""
        repo = directory.path
        url = git(repo, "config", "--get", "remote.origin.url", check=False)
        command = command_for(url)
        if command is None:
            log(False, f"Not releasing: there's no release command for {url or 'no origin'}")
            return False
        log.begin(f"Running `{Path(command).name} release {LEVEL}`")
        result = subprocess.run(
            [command, "release", str(repo), LEVEL], capture_output=True, text=True
        )
        if result.returncode != 0:
            log(False, "Release failed", *(result.stderr + result.stdout).strip().splitlines())
            return False
        # Its status line repeats what this one says.
        details = [line for line in result.stdout.splitlines() if not line.startswith("✅")]
        log(True, "Released", *details)
        return True


def command_for(url: str) -> str | None:
    """The command that releases the repository at origin url, or None for a host with none."""
    if "github.com" in url:
        return github.GITHUB
    if "bitbucket.org" in url:
        return BITBUCKET
    return None
