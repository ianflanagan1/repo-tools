"""📌 A Python project's uv.lock that `uv lock --upgrade` would change, upgraded by repo-fix,
committed and pushed.

Only the trunk is upgraded, and only with local integration, where repo-fix commits to the trunk
and pushes it: an upgrade on each branch would conflict when they land, and where work goes by pull
request nothing is committed on the trunk. The upgrade comes after the branch is level with its
upstream, so the commit goes on top of what's there. uv runs from the project's devbox.

The check reads the network. It's skipped for a repository whose fetch failed, as nothing could be
pushed there.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path

from repo_list.git import git, in_progress, run
from repo_list.plugin import Log, Plugin, Problem, Stage, count
from repo_list.plugins import sync
from repo_list.scan import Directory

DEVBOX = "devbox"
MESSAGE = "Upgrade the locked dependencies"
_CHANGES = ("Update ", "Add ", "Remove ")


@dataclass(frozen=True)
class Upgradable:
    upgrades: tuple[str, ...]
    """Each package uv would change, as it says so, such as "Update ruff v0.1.0 -> v0.2.0"."""

    def describe(self) -> str:
        return f"📌 {count(len(self.upgrades), 'upgrade')} for uv.lock"


@dataclass(frozen=True)
class NoDevbox:
    def describe(self) -> str:
        return "📌 no devbox.json to run uv in"


@dataclass(frozen=True)
class LockCheckFailed:
    """uv couldn't tell what an upgrade would change."""

    def describe(self) -> str:
        return "📌 uv.lock check failed"


class Lock(Plugin):
    name = "lock"
    stage = Stage.LOCK

    def check(self, directory: Directory) -> list[Problem]:
        """What upgrading the trunk's uv.lock would change, when the trunk is checked out here
        with local integration."""
        place = directory.place
        repo = directory.path
        if directory.fetch_failed or place is None or place.integration is None:
            return []
        if place.integration.by_pull_request or place.head is None or place.head != place.trunk:
            return []
        if not (repo / "uv.lock").is_file():
            return []
        if not (repo / "devbox.json").is_file():
            return [NoDevbox()]
        result = _uv_lock_upgrade(repo, "--dry-run")
        if result.returncode != 0:
            return [LockCheckFailed()]
        found = upgrades(result.stderr)
        return [Upgradable(tuple(found))] if found else []

    def fix(self, directory: Directory, problems: list[Problem], log: Log) -> bool:
        """Upgrades uv.lock, commits it alone and pushes the trunk. Says whether that worked."""
        place = directory.place
        repo = directory.path
        if place is None or place.integration is None:
            return True
        if not any(isinstance(p, Upgradable) for p in problems):
            return True
        if operation := in_progress(repo):
            log(False, f"Not upgrading uv.lock: {operation} is in progress")
            return False
        facts = sync.gather(directory)
        if behind := next((b for b in facts.branches if b.here and b.behind), None):
            upstream = facts.upstreams[behind.name]
            log(False, f"Not upgrading uv.lock: {behind.name} is behind {upstream}")
            return False

        log.begin("Running `uv lock --upgrade`")
        result = _uv_lock_upgrade(repo)
        if result.returncode != 0:
            said = (result.stderr + result.stdout).strip().splitlines()
            log(False, "uv lock --upgrade failed", *said)
            return False
        if not git(repo, "status", "--porcelain", "--", "uv.lock"):
            return True
        done = upgrades(result.stderr)
        body = ["--message", "\n".join(done)] if done else []
        committed = run(repo, "commit", "--quiet", "--message", MESSAGE, *body, "--", "uv.lock")
        if committed.returncode != 0:
            log(False, "Commit of uv.lock failed", *committed.stderr.strip().splitlines())
            return False
        log(True, f"Committed {git(repo, 'log', '-1', '--format=%h %s')}", *done)
        sync.push_all(directory, place.integration, log)
        return True


def upgrades(said: str) -> list[str]:
    """Each package uv says it changes in the lock, from what `uv lock` writes to stderr."""
    return [line.strip() for line in said.splitlines() if line.startswith(_CHANGES)]


def _uv_lock_upgrade(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Runs `uv lock --upgrade` with args, from the project's devbox, in the project."""
    command = [DEVBOX, "run", "--quiet", "--config", str(repo), "--", "uv", "lock", "--upgrade"]
    return subprocess.run([*command, *args], cwd=repo, capture_output=True, text=True)
