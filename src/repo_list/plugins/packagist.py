"""🐘 A package of your vendor's that Packagist lacks, or lacks versions or branches of, published
and updated there with the packagist command.

The check reads the network. It's skipped for a repository whose fetch failed, as what's on
origin to compare Packagist with isn't known.
"""

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from cli_kit.outcome import Failure

from repo_list.git import git
from repo_list.plugin import Log, Plugin, Problem, Stage
from repo_list.scan import Folder
from repo_tools.packagist import api as packagist

PACKAGIST = str(Path(sys.prefix) / "bin" / "packagist")


@dataclass(frozen=True)
class NotOnPackagist:
    def describe(self) -> str:
        return "🐘 not on Packagist"


@dataclass(frozen=True)
class PackagistBehind:
    """Version tags, and branches at a commit, on origin that Packagist doesn't offer yet."""

    lacking: tuple[str, ...]

    def describe(self) -> str:
        return f"🐘 Packagist lacks {', '.join(self.lacking)}"


@dataclass(frozen=True)
class PackagistFailed:
    """Packagist, or the ls-remote of origin to compare it with, couldn't be read."""

    def describe(self) -> str:
        return "🐘 Packagist check failed"


class Packagist(Plugin):
    name = "packagist"
    stage = Stage.AFTER_PUSH

    def __init__(self, vendor: str) -> None:
        self.vendor = vendor

    def check(self, folder: Folder) -> list[Problem]:
        """What Packagist lacks of the repository, if it is a package of the vendor's with an
        origin."""
        repo = folder.path
        if folder.fetch_failed:
            return []
        package = package_name(repo, self.vendor)
        if package is None or "origin" not in git(repo, "remote").split():
            return []
        try:
            lacking = packagist.lacks(package, repo)
        except Failure:
            return [PackagistFailed()]
        if lacking is None:
            return [NotOnPackagist()]
        return [PackagistBehind(tuple(lacking))] if lacking else []

    def fix(self, folder: Folder, problems: list[Problem], log: Log) -> bool:
        if problems == [PackagistFailed()]:
            return True
        for command, done in (
            ("publish", "Published on Packagist"),
            ("update", "Updated on Packagist"),
        ):
            if not run(command, folder, done, log):
                return False
        return True


def package_name(repo: Path, vendor: str) -> str | None:
    """The name in the repository's composer.json, if it is a package of vendor's."""
    try:
        name = json.loads((repo / "composer.json").read_text()).get("name")
    except (OSError, ValueError, AttributeError):
        return None
    if isinstance(name, str) and name.startswith(f"{vendor}/"):
        return name
    return None


def run(command: str, folder: Folder, done: str, log: Log) -> bool:
    """Runs a packagist command on the repository, and logs it if it changed anything. Says
    whether it worked."""
    result = subprocess.run([PACKAGIST, command, str(folder.path)], capture_output=True, text=True)
    if result.returncode != 0:
        log(
            False,
            f"Packagist {command} failed",
            *(result.stderr + result.stdout).strip().splitlines(),
        )
        return False
    lines = result.stdout.splitlines()
    if any(line.startswith("✅") for line in lines):
        log(True, done, *(line for line in lines if not line.startswith("✅")))
    return True
