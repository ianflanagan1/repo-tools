"""🔌 A repository with no remote, published with `github publish`."""

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from repo_list.git import git
from repo_list.plugin import Log, Plugin, Problem, Stage
from repo_list.scan import Folder

GITHUB = str(Path(sys.prefix) / "bin" / "github")


@dataclass(frozen=True)
class NoRemote:
    def describe(self) -> str:
        return "🔌 no remote"


class GitHub(Plugin):
    name = "github"
    stage = Stage.PUBLISH

    def __init__(self, wait_for_ci: bool) -> None:
        self.wait_for_ci = wait_for_ci

    def check(self, folder: Folder) -> list[Problem]:
        return [] if git(folder.path, "remote") else [NoRemote()]

    def fix(self, folder: Folder, problems: list[Problem], log: Log) -> bool:
        """Publishes the repository with github publish. Says whether it worked."""
        command = [GITHUB, "publish", str(folder.path)]
        if not self.wait_for_ci:
            command.append("--no-ci-wait")
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            log(False, "Publish failed", *(result.stderr + result.stdout).strip().splitlines())
            return False
        # Its status line repeats what this one says.
        details = [line for line in result.stdout.splitlines() if not line.startswith("✅")]
        log(True, "Published", *details)
        return True
