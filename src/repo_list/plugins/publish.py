"""🔌 A repository with no remote, published on the git host its .config/ianf-repo-tools.toml puts
origin on, with `github publish` or `bitbucket publish`, public or private as its visibility says.
A repository that names no git host, or no visibility, is asked for it before it's fixed (see
repo_list.ask_git_host); one left unset isn't published. One whose
settings keep it on this computer only, with git-host none, has no remote on purpose, which isn't a
problem."""

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import assert_never

from repo_list import git_hosts
from repo_list.git import git
from repo_list.git_hosts import GitHost, LocalOnly, Visibility
from repo_list.plugin import Log, Plugin, Problem, Stage
from repo_list.scan import SETTINGS, Directory

GITHUB = str(Path(sys.prefix) / "bin" / "github")
BITBUCKET = str(Path(sys.prefix) / "bin" / "bitbucket")


def command(git_host: GitHost) -> str:
    """The command that publishes, and releases, a repository on git_host."""
    match git_host:
        case GitHost.GITHUB:
            return GITHUB
        case GitHost.BITBUCKET:
            return BITBUCKET
        case _:
            assert_never(git_host)


@dataclass(frozen=True)
class NoRemote:
    def describe(self) -> str:
        return "🔌 no remote"


class Publish(Plugin):
    name = "publish"
    stage = Stage.PUBLISH

    def __init__(self, wait_for_ci: bool) -> None:
        self.wait_for_ci = wait_for_ci

    def check(self, directory: Directory) -> list[Problem]:
        if directory.place and isinstance(directory.place.origin, LocalOnly):
            return []
        return [] if git(directory.path, "remote") else [NoRemote()]

    def fix(self, directory: Directory, problems: list[Problem], log: Log) -> bool:
        """Publishes the repository on its origin's git host. Says whether it worked."""
        place = directory.place
        git_host = place.origin if place else None
        if not isinstance(git_host, GitHost):
            log(False, f"Not published: choose a git host when asked, or set one in {SETTINGS}")
            return False
        visibility = place.visibility if place else None
        if visibility is None:
            log(False, f"Not published: choose who can see it when asked, or set it in {SETTINGS}")
            return False
        name = Path(command(git_host)).name
        run = [command(git_host), "publish", str(directory.path), *_flags(visibility)]
        if not self.wait_for_ci:
            run.append("--no-ci-wait")
        log.begin(
            f"Publishing on {git_hosts.title(git_host)} with `{name} publish`"
            + (", then waiting for CI" if self.wait_for_ci else "")
        )
        result = subprocess.run(run, capture_output=True, text=True)
        if result.returncode != 0:
            log(False, "Publish failed", *(result.stderr + result.stdout).strip().splitlines())
            return False
        # Its status line repeats what this one says.
        details = [line for line in result.stdout.splitlines() if not line.startswith("✅")]
        log(True, "Published", *details)
        return True


def _flags(visibility: Visibility) -> list[str]:
    """What tells `publish` who can see the repository it makes."""
    match visibility:
        case Visibility.PUBLIC:
            return []
        case Visibility.PRIVATE:
            return ["--private"]
        case _:
            assert_never(visibility)
