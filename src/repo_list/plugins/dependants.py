"""🔗 A project whose lock file holds a package of yours, from another repository here, at less than
its latest: for a package released by version tag, its highest version tag; for a Python package
pinned from a git branch, the trunk as pushed. repo-fix upgrades just those packages with the
ecosystem's own tool, run in the project's devbox, then commits the lock files alone, for Go its
go.mod and go.sum, and pushes them.

repo-fix fixes each repository after those it pins, releasing and publishing them first, so the
upgrade finds what they just released. Only the trunk is upgraded, with direct integration, as
uv.lock's 📌 is. A version the project's constraint excludes, such as a new major one, needs its
manifest changed, which is left for you.
"""

from collections.abc import Mapping, Set
from dataclasses import dataclass
from pathlib import Path

from git_default_branch import default_branch

from repo_list import ecosystems
from repo_list.git import git, run
from repo_list.plugin import Log, Plugin, Problem, Stage
from repo_list.plugins import lock, sync
from repo_list.scan import Directory
from repo_tools import packages, versions
from repo_tools.packages import Ecosystem, Name


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
    stage = Stage.LOCK

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
        own = packages.names(repo)
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

    def fix(self, directory: Directory, problems: list[Problem], log: Log) -> bool:
        """Upgrades each lock file behind, commits each alone, and pushes the trunk. Says whether
        it could start."""
        place = directory.place
        behind = [p for p in problems if isinstance(p, Behind)]
        if place is None or place.integration is None or not behind:
            return True
        if not lock.ready_to_commit(directory, "upgrading your packages", log):
            return False
        committed = [_upgrade(directory, b, log) for b in behind]
        if any(committed):
            sync.push_all(directory, place.integration, log)
        return True


def _upgrade(directory: Directory, behind: Behind, log: Log) -> bool:
    """Upgrades the packages behind in their lock files and commits them alone. Says whether it
    committed."""
    repo = directory.path
    lock_file = ecosystems.lock_file(behind.ecosystem)
    tool = ecosystems.tool(behind.ecosystem)
    if not (repo / "devbox.json").is_file():
        log(False, f"Not upgrading {lock_file}: there's no devbox.json to run {tool} in")
        return False
    names = [u.name for u in behind.upgrades]
    command = ecosystems.upgrade_command(behind.ecosystem, names)
    log.begin(f"Running `{' '.join(command)}`")
    result = lock.in_devbox(repo, *command)
    if result.returncode != 0:
        said = (result.stderr + result.stdout).strip().splitlines()
        log(False, f"{tool} failed to upgrade {lock_file}", *said)
        return False
    changed = [f for f in ecosystems.lock_files(behind.ecosystem) if _changed(repo, f)]
    if not changed:
        log(
            False,
            f"{tool} left {lock_file} as it was; its constraint may exclude the latest",
            *(u.describe() for u in behind.upgrades),
        )
        return False
    body = "\n".join(u.describe() for u in behind.upgrades)
    message = ["--message", f"Upgrade {', '.join(names)}", "--message", body]
    # One the upgrade made, such as a go.sum, has to be added before it can be committed.
    run(repo, "add", "--", *changed)
    committed = run(repo, "commit", "--quiet", *message, "--", *changed)
    if committed.returncode != 0:
        log(False, f"Commit of {lock_file} failed", *committed.stderr.strip().splitlines())
        return False
    subject = git(repo, "log", "-1", "--format=%h %s")
    log(True, f"Committed {subject}", *(u.describe() for u in behind.upgrades))
    return True


def _changed(repo: Path, path: str) -> bool:
    return bool(git(repo, "status", "--porcelain", "--", path))


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
