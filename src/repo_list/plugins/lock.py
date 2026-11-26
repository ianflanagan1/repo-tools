"""📌 A project's lock files, upgraded in full by repo-fix, with what they hold installed.

On the trunk with direct integration, each lock file whose tool would change it, upgrading every
package as far as the manifest's constraints allow, is upgraded, and what it then holds is
installed. A project with a `check` task has it run next: if that fails, the lock files go back as
they were, and so does what's installed. Otherwise they're committed together and pushed. A push
that fails leaves the commit, to push next time, and stops the repository there, so nothing is
released on top of it.

Only the trunk is upgraded: an upgrade on each branch would conflict when they land, and where work
goes by pull request nothing is committed on the trunk. The upgrade comes after the branch is level
with its upstream, so the commit goes on top of what's there. repo-fix fixes each repository after
those it pins, so an upgrade finds what they just released.

In any worktree, dependencies that were installed but differ from what the lock file holds, as
after a fast-forward brought in an upgrade made elsewhere, are installed again. Ones never installed
are left so. Go's are never behind, as its module cache is shared, and fills as each project builds.

Only lock files at the top of the repository count, and each tool runs from the project's devbox,
but for Nix, which devbox itself runs on, so is the machine's own.
The upgrade check reads the network. It's skipped for a repository whose fetch failed, as nothing
could be pushed there.
"""

import json
import shlex
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from repo_list import ecosystems
from repo_list.git import git, in_progress, run
from repo_list.plugin import Log, Plugin, Problem, Stage, count
from repo_list.plugins import sync
from repo_list.scan import Directory
from repo_tools.dependencies import Ecosystem

DEVBOX = "devbox"
MESSAGE = "Upgrade the locked dependencies"
CHECK_TASK = "check"
CHECK_LINES_SHOWN = 20
"""How many of the last lines a failed check task wrote are shown."""


@dataclass(frozen=True)
class Upgradable:
    ecosystem: Ecosystem
    upgrades: tuple[str, ...]
    """Each package the upgrade would change, as the tool says so, such as "Update ruff v0.1.0 ->
    v0.2.0"."""

    def describe(self) -> str:
        lock_file = ecosystems.lock_file(self.ecosystem)
        return f"📌 {count(len(self.upgrades), 'upgrade')} for {lock_file}"


@dataclass(frozen=True)
class InstallBehind:
    """What's installed differs from what the lock file holds."""

    ecosystem: Ecosystem

    def describe(self) -> str:
        lock_file = ecosystems.lock_file(self.ecosystem)
        return f"📌 {ecosystems.install_dir(self.ecosystem)} behind {lock_file}"


@dataclass(frozen=True)
class NoDevbox:
    ecosystem: Ecosystem

    def describe(self) -> str:
        return f"📌 no devbox.json to run {ecosystems.tool(self.ecosystem)} in"


@dataclass(frozen=True)
class LockCheckFailed:
    """The tool couldn't tell what an upgrade would change."""

    ecosystem: Ecosystem
    reason: str
    """The last line the tool wrote, which says why, such as that the upgrade needs a newer Go
    than the project's devbox has; or "" if it wrote nothing."""

    def describe(self) -> str:
        failed = f"📌 {ecosystems.lock_file(self.ecosystem)} check failed"
        return f"{failed}: {self.reason}" if self.reason else failed


class Lock(Plugin):
    name = "lock"
    stage = Stage.LOCK

    def __init__(self, own_go_modules: Sequence[str]) -> None:
        self.own_go_modules = own_go_modules
        """The path of each Go module here, which an upgrade asks its repository for directly."""

    def check(self, directory: Directory) -> list[Problem]:
        """For each lock file, what upgrading it would change, when the trunk is checked out here
        with direct integration, and whether what's installed differs from what it holds."""
        repo = directory.path
        trunk = on_direct_trunk(directory)
        has_devbox = (repo / "devbox.json").is_file()
        found: list[Problem] = []
        for ecosystem in _locked_ecosystems(repo):
            if not has_devbox and ecosystems.runs_in_devbox(ecosystem):
                found.extend([NoDevbox(ecosystem)] if trunk else [])
                continue
            if trunk:
                found.extend(self._upgradable(repo, ecosystem))
            if _installed_behind(repo, ecosystem):
                found.append(InstallBehind(ecosystem))
        return found

    def fix(self, directory: Directory, problems: list[Problem], log: Log) -> bool:
        """Upgrades the lock files, installs what they hold, runs the check task, then commits them
        and pushes the trunk; and installs again what's behind a lock file that wasn't upgraded.
        Says whether that worked."""
        place = directory.place
        upgradable = [p.ecosystem for p in problems if isinstance(p, Upgradable)]
        behind = [p.ecosystem for p in problems if isinstance(p, InstallBehind)]
        if upgradable and place is not None and place.integration is not None:
            if not ready_to_commit(directory, "upgrading the lock files", log):
                return False
            if not self._upgrade(directory.path, upgradable, log):
                return False
            if not sync.push_all(directory, place.integration, log):
                return False
        return all(_install(directory.path, e, log) for e in behind if e not in upgradable)

    def _upgradable(self, repo: Path, ecosystem: Ecosystem) -> list[Problem]:
        """What upgrading the lock file would change, from a dry run."""
        lock_file = ecosystems.lock_file(ecosystem)
        before = (repo / lock_file).read_text()
        with tempfile.TemporaryDirectory() as scratch_dir:
            scratch = Path(scratch_dir)
            for name in ecosystems.dry_run_copies(ecosystem):
                if (repo / name).is_file():
                    shutil.copy(repo / name, scratch / name)
            command = ecosystems.dry_run_command(ecosystem, self.own_go_modules, scratch)
            result = _run_tool(repo, ecosystem, command)
            copy = scratch / lock_file
            after = copy.read_text() if copy.is_file() else before
        if result.returncode != 0:
            said = (result.stdout + result.stderr).strip().splitlines()
            return [LockCheckFailed(ecosystem, said[-1].strip() if said else "")]
        found = ecosystems.changes(ecosystem, result.stderr, before, after)
        return [Upgradable(ecosystem, tuple(found))] if found else []

    def _upgrade(self, repo: Path, upgradable: list[Ecosystem], log: Log) -> bool:
        """Upgrades the lock files, installs what they hold, runs the check task and commits them.
        Leaves the lock files and what's installed as they were if any of that fails, and says
        whether it didn't."""
        before = {e: (repo / ecosystems.lock_file(e)).read_text() for e in upgradable}
        said: dict[Ecosystem, str] = {}
        for ecosystem in upgradable:
            command = ecosystems.upgrade_command(ecosystem, self.own_go_modules)
            log.begin(f"Running `{shlex.join(command)}`")
            result = _run_tool(repo, ecosystem, command)
            if result.returncode != 0:
                lock_file = ecosystems.lock_file(ecosystem)
                details = (result.stderr + result.stdout).strip().splitlines()
                log(False, f"{ecosystems.tool(ecosystem)} failed to upgrade {lock_file}", *details)
                _restore(repo, _changed(repo, upgradable))
                return False
            said[ecosystem] = result.stderr
        changed = _changed(repo, upgradable)
        upgraded = [e for e in upgradable if set(ecosystems.lock_files(e)) & set(changed)]
        if not upgraded:
            return True
        if not all(_install(repo, e, log) for e in upgraded):
            _restore(repo, changed)
            return False
        if not _passes_check(repo, log):
            _restore(repo, changed)
            for ecosystem in upgraded:
                _install(repo, ecosystem, log)
            return False
        done = [
            line
            for e in upgraded
            for line in ecosystems.changes(
                e, said[e], before[e], (repo / ecosystems.lock_file(e)).read_text()
            )
        ]
        # One the upgrade made, such as a go.sum, has to be added before it can be committed.
        run(repo, "add", "--", *changed)
        body = ["--message", "\n".join(done)] if done else []
        committed = run(repo, "commit", "--quiet", "--message", MESSAGE, *body, "--", *changed)
        if committed.returncode != 0:
            log(False, "Commit of the lock files failed", *committed.stderr.strip().splitlines())
            return False
        log(True, f"Committed {git(repo, 'log', '-1', '--format=%h %s')}", *done)
        return True


def on_direct_trunk(directory: Directory) -> bool:
    """Whether the directory has the trunk checked out with direct integration, where repo-fix
    commits to the trunk and pushes it, and its fetch didn't fail, so it can be pushed."""
    place = directory.place
    if directory.fetch_failed or place is None or place.integration is None:
        return False
    return (
        not place.integration.by_pull_request
        and place.head is not None
        and (place.head == place.trunk)
    )


def ready_to_commit(directory: Directory, doing: str, log: Log) -> bool:
    """Whether a commit can go on top of what's checked out: no operation is in progress, and the
    branch isn't behind its upstream. Logs why not, as "Not {doing}: ..."."""
    repo = directory.path
    if operation := in_progress(repo):
        log(False, f"Not {doing}: {operation} is in progress")
        return False
    facts = sync.gather(directory)
    if behind := next((b for b in facts.branches if b.here and b.behind), None):
        upstream = facts.upstreams[behind.name]
        log(False, f"Not {doing}: {behind.name} is behind {upstream}")
        return False
    return True


def in_devbox(repo: Path, *command: str) -> subprocess.CompletedProcess[str]:
    """Runs command from the project's devbox, in the project."""
    devbox = [DEVBOX, "run", "--quiet", "--config", str(repo), "--"]
    return subprocess.run([*devbox, *command], cwd=repo, capture_output=True, text=True)


def _run_tool(
    repo: Path, ecosystem: Ecosystem, command: list[str]
) -> subprocess.CompletedProcess[str]:
    """Runs the ecosystem's command in the project: from its devbox, or for a tool that's the
    machine's own, as it is."""
    if ecosystems.runs_in_devbox(ecosystem):
        return in_devbox(repo, *command)
    return subprocess.run(command, cwd=repo, capture_output=True, text=True)


def task_names(listing: str) -> set[str]:
    """The name of each task in what `task --list-all --json` wrote, or none if it can't be
    parsed."""
    try:
        tasks = json.loads(listing).get("tasks")
    except (ValueError, AttributeError):
        return set()
    if not isinstance(tasks, list):
        return set()
    return {t["name"] for t in tasks if isinstance(t, dict) and isinstance(t.get("name"), str)}


def _locked_ecosystems(repo: Path) -> list[Ecosystem]:
    return [e for e in Ecosystem if (repo / ecosystems.lock_file(e)).is_file()]


def _installed_behind(repo: Path, ecosystem: Ecosystem) -> bool:
    """Whether the dependencies were installed, and differ from what the lock file holds."""
    where = ecosystems.install_dir(ecosystem)
    if where is None or not (repo / where).is_dir():
        return False
    lock = (repo / ecosystems.lock_file(ecosystem)).read_text()
    if record := ecosystems.installed_record(ecosystem):
        path = repo / where / record
        return not path.is_file() or ecosystems.installed_behind(ecosystem, lock, path.read_text())
    command = ecosystems.check_command(ecosystem)
    return command is not None and in_devbox(repo, *command).returncode != 0


def _install(repo: Path, ecosystem: Ecosystem, log: Log) -> bool:
    """Installs what the lock file holds, and says whether that worked."""
    lock_file = ecosystems.lock_file(ecosystem)
    command = ecosystems.install_command(ecosystem)
    log.begin(f"Running `{shlex.join(command)}`")
    result = _run_tool(repo, ecosystem, command)
    if result.returncode != 0:
        details = (result.stderr + result.stdout).strip().splitlines()
        log(False, f"{ecosystems.tool(ecosystem)} failed to install {lock_file}", *details)
        return False
    log(True, f"Installed {lock_file}")
    return True


def _passes_check(repo: Path, log: Log) -> bool:
    """Whether the project's check task passes, or it has none. Logs the end of what it wrote if
    it fails."""
    listed = in_devbox(repo, "task", "--list-all", "--json")
    if listed.returncode != 0 or CHECK_TASK not in task_names(listed.stdout):
        return True
    log.begin(f"Running `task {CHECK_TASK}`")
    result = in_devbox(repo, "task", CHECK_TASK)
    if result.returncode == 0:
        return True
    said = (result.stdout + result.stderr).strip().splitlines()[-CHECK_LINES_SHOWN:]
    log(False, f"task {CHECK_TASK} failed after the upgrade, so it was undone", *said)
    return False


def _changed(repo: Path, upgraded: list[Ecosystem]) -> list[str]:
    """Each of the ecosystems' lock files that differs from HEAD, or is new."""
    files = [f for e in upgraded for f in ecosystems.lock_files(e)]
    return [f for f in files if git(repo, "status", "--porcelain", "--", f)]


def _restore(repo: Path, files: list[str]) -> None:
    """Puts the files back as HEAD has them, removing any HEAD lacks."""
    for name in files:
        if run(repo, "cat-file", "-e", f"HEAD:{name}").returncode == 0:
            run(repo, "checkout", "HEAD", "--", name)
        else:
            (repo / name).unlink()
