"""🟥 A package of your scope's that npm lacks, or lacks version tags of, published there and
waited for with the npmjs command.

The check reads the network. It's skipped for a repository whose fetch failed, as what's on
origin to compare npm with isn't known.
"""

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from cli_kit.outcome import Failure

from repo_list.git import git
from repo_list.plugin import Log, Plugin, Problem, Stage
from repo_list.scan import Directory
from repo_tools.npmjs import api as npm

NPMJS = str(Path(sys.prefix) / "bin" / "npmjs")


@dataclass(frozen=True)
class NotOnNpm:
    def describe(self) -> str:
        return "🟥 not on npm"


@dataclass(frozen=True)
class NpmBehind:
    """Version tags on origin that npm doesn't have yet."""

    lacking: tuple[str, ...]

    def describe(self) -> str:
        return f"🟥 npm lacks {', '.join(self.lacking)}"


@dataclass(frozen=True)
class NpmFailed:
    """npm, or the ls-remote of origin to compare it with, couldn't be read."""

    def describe(self) -> str:
        return "🟥 npm check failed"


class Npm(Plugin):
    name = "npm"
    stage = Stage.AFTER_PUSH

    def __init__(self, scope: str) -> None:
        self.scope = scope

    def check(self, directory: Directory) -> list[Problem]:
        """What npm lacks of the repository, if it is a public package of the scope's with an
        origin."""
        repo = directory.path
        if directory.fetch_failed:
            return []
        package = package_name(repo, self.scope)
        if package is None or "origin" not in git(repo, "remote").split():
            return []
        try:
            lacking = npm.lacks(package, repo)
        except Failure:
            return [NpmFailed()]
        if lacking is None:
            return [NotOnNpm()]
        return [NpmBehind(tuple(lacking))] if lacking else []

    def fix(self, directory: Directory, problems: list[Problem], log: Log) -> bool:
        match problems:
            case [NpmFailed()]:
                return True
            case [NotOnNpm()]:
                return publish(directory, log) and wait(directory, (), log)
            case [NpmBehind(lacking)]:
                return wait(directory, lacking, log)
        return True


def package_name(repo: Path, scope: str) -> str | None:
    """The name in the repository's package.json, if it is a package of scope's that isn't
    private, which npm takes as never to be published."""
    try:
        manifest = json.loads((repo / "package.json").read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(manifest, dict) or manifest.get("private") is True:
        return None
    name = manifest.get("name")
    return name if isinstance(name, str) and name.startswith(f"{scope}/") else None


def publish(directory: Directory, log: Log) -> bool:
    """Runs `npmjs publish` with the terminal, as npm asks for one-time passwords. Says whether
    it worked."""
    if subprocess.run([NPMJS, "publish", str(directory.path)]).returncode != 0:
        log(False, "npm publish failed")
        return False
    log(True, "Published on npm")
    return True


def wait(directory: Directory, lacking: tuple[str, ...], log: Log) -> bool:
    """Runs `npmjs wait` until npm has every version tag, and logs what it waited for. Says
    whether it worked."""
    result = subprocess.run([NPMJS, "wait", str(directory.path)], capture_output=True, text=True)
    if result.returncode != 0:
        log(False, "npm wait failed", *(result.stderr + result.stdout).strip().splitlines())
        return False
    lines = result.stdout.splitlines()
    if lacking and any(line.startswith("✅") for line in lines):
        log(
            True,
            f"npm published {', '.join(lacking)}",
            *(line for line in lines if not line.startswith("✅")),
        )
    return True
