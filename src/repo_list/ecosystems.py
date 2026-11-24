"""Each ecosystem a package can be in, such as Composer, and what it takes there to release a
package of yours, to upgrade a project's lock file and to install what it holds.

Ecosystem is a closed family: each function here matches on it, so a new one fails the type
check until each has a case for it. The flags that choose ecosystems are made from it too, so a
new one gets a flag of its own and is among those --dependencies chooses.
"""

import argparse
import json
import tomllib
from collections.abc import Callable, Iterable, Sequence, Set
from pathlib import Path, PurePosixPath
from typing import assert_never
from urllib.parse import parse_qs, urlsplit

from repo_list import config
from repo_list.config import Config
from repo_tools import dependencies, versions
from repo_tools.dependencies import Ecosystem, Name

DEPENDENCIES = "--dependencies"


def flags(ecosystem: Ecosystem) -> tuple[str, ...]:
    """The flag that chooses the ecosystem, its long form last."""
    match ecosystem:
        case Ecosystem.COMPOSER:
            return ("--packagist",)
        case Ecosystem.NPM:
            return ("--npm",)
        case Ecosystem.PYTHON:
            return ("--python",)
        case Ecosystem.GO:
            return ("--go",)
        case Ecosystem.NIX:
            return ("--nix",)
        case _:
            assert_never(ecosystem)


def packages_of(ecosystem: Ecosystem) -> str:
    """Which packages in the ecosystem are yours, for a flag's help."""
    match ecosystem:
        case Ecosystem.COMPOSER:
            return "each package of your Packagist vendor's"
        case Ecosystem.NPM:
            return "each package of your npm scope's"
        case Ecosystem.PYTHON:
            return "each Python package another repository here pins"
        case Ecosystem.GO:
            return "each Go module another repository here requires"
        case Ecosystem.NIX:
            return "each Nix flake here"
        case _:
            assert_never(ecosystem)


def add_flags(
    parser: argparse.ArgumentParser, help: Callable[[Ecosystem], str], every: str
) -> None:
    """Adds a flag for each ecosystem, with help(ecosystem) as its help, then --dependencies,
    which chooses them all, with every as its help."""
    for ecosystem in Ecosystem:
        parser.add_argument(
            *flags(ecosystem), dest=ecosystem.value, action="store_true", help=help(ecosystem)
        )
    parser.add_argument(DEPENDENCIES, action="store_true", help=every)


def chosen(args: argparse.Namespace) -> frozenset[Ecosystem]:
    """The ecosystems the flags add_flags added choose."""
    return frozenset(e for e in Ecosystem if args.dependencies or getattr(args, e.value))


def missing_setting(ecosystem: Ecosystem, settings: Config) -> tuple[str, str] | None:
    """The setting in config.toml the ecosystem needs to judge which packages are yours, and what
    it is, when settings lack it."""
    match ecosystem:
        case Ecosystem.COMPOSER:
            return None if settings.packagist_vendor else ("packagist.vendor", "your vendor name")
        case Ecosystem.NPM:
            return None if settings.npm_scope else ("npm.scope", "your scope")
        case Ecosystem.PYTHON | Ecosystem.GO | Ecosystem.NIX:
            return None
        case _:
            assert_never(ecosystem)


def settings_for(parser: argparse.ArgumentParser, ecosystems: Set[Ecosystem]) -> Config:
    """The settings for a command that parser parsed, ending it with a usage error when they
    can't be read, or lack what one of the ecosystems chosen needs."""
    try:
        settings = config.load()
    except config.ConfigError as error:
        parser.error(str(error))
    example = config.CONFIG.with_name("config.example.toml").name
    for ecosystem in (e for e in Ecosystem if e in ecosystems):
        if missing := missing_setting(ecosystem, settings):
            key, what = missing
            flag = flags(ecosystem)[-1]
            parser.error(f"{flag} needs {what}: set {key} in {config.CONFIG}, as {example} shows")
    return settings


def is_yours(name: Name, settings: Config) -> bool:
    """Whether the package is yours: your vendor's or scope's, or for Python and Go, as a Python
    project or Go module is a dependency only once another of the repositories here pins it, any;
    and any flake, as one of the repositories here."""
    match name.ecosystem:
        case Ecosystem.COMPOSER:
            vendor = settings.packagist_vendor
            return vendor is not None and name.name.startswith(f"{vendor.lower()}/")
        case Ecosystem.NPM:
            scope = settings.npm_scope
            return scope is not None and name.name.startswith(f"{scope}/")
        case Ecosystem.PYTHON | Ecosystem.GO | Ecosystem.NIX:
            return True
        case _:
            assert_never(name.ecosystem)


def yours(
    project: Path,
    ecosystems: Set[Ecosystem],
    settings: Config,
    pinned: Set[Name],
    offering: Set[Path],
) -> set[Name]:
    """The names of the packages of yours the project is, in the ecosystems chosen, given every
    name the projects here pin, and every project whose flake has an output for other flakes."""
    found = (dependencies.name_of(p) for p in dependencies.discover(project, pinned, offering))
    return {
        name
        for name in found
        if name is not None and name.ecosystem in ecosystems and is_yours(name, settings)
    }


def providers(
    projects: Iterable[Path],
    ecosystems: Set[Ecosystem],
    settings: Config,
    pinned: Set[Name],
    offering: Set[Path],
) -> dict[Name, Path]:
    """The project each package of yours in the ecosystems chosen comes from, by its name: the
    first, where several are the same package, as a repository's worktrees are."""
    found: dict[Name, Path] = {}
    for project in projects:
        for name in yours(project, ecosystems, settings, pinned, offering):
            found.setdefault(name, project)
    return found


def releases_by_tag(ecosystem: Ecosystem) -> bool:
    """Whether a new version of a package reaches the projects that pin it by a version tag, or
    else, as a Python package or a flake pinned from git, by its commit alone."""
    match ecosystem:
        case Ecosystem.COMPOSER | Ecosystem.NPM | Ecosystem.GO:
            return True
        case Ecosystem.PYTHON | Ecosystem.NIX:
            return False
        case _:
            assert_never(ecosystem)


def lock_files(ecosystem: Ecosystem) -> tuple[str, ...]:
    """The files an upgrade changes, the one that holds each package's version first. Go's go.mod
    is its manifest too, but holds the versions, as a lock file does."""
    match ecosystem:
        case Ecosystem.COMPOSER:
            return ("composer.lock",)
        case Ecosystem.NPM:
            return ("package-lock.json",)
        case Ecosystem.PYTHON:
            return ("uv.lock",)
        case Ecosystem.GO:
            return ("go.mod", "go.sum")
        case Ecosystem.NIX:
            return ("flake.lock",)
        case _:
            assert_never(ecosystem)


def lock_file(ecosystem: Ecosystem) -> str:
    """The file that holds the version of each package."""
    return lock_files(ecosystem)[0]


def tool(ecosystem: Ecosystem) -> str:
    """The command that upgrades the ecosystem's lock file and installs what it holds."""
    match ecosystem:
        case Ecosystem.COMPOSER:
            return "composer"
        case Ecosystem.NPM:
            return "npm"
        case Ecosystem.PYTHON:
            return "uv"
        case Ecosystem.GO:
            return "go"
        case Ecosystem.NIX:
            return "nix"
        case _:
            assert_never(ecosystem)


def runs_in_devbox(ecosystem: Ecosystem) -> bool:
    """Whether the tool runs from the project's devbox, or else, as Nix, which devbox itself runs
    on, is the machine's own, so needs no devbox.json."""
    match ecosystem:
        case Ecosystem.COMPOSER | Ecosystem.NPM | Ecosystem.PYTHON | Ecosystem.GO:
            return True
        case Ecosystem.NIX:
            return False
        case _:
            assert_never(ecosystem)


LOCK_FILES = frozenset(f for e in Ecosystem for f in lock_files(e))


def needs_release(changed: Iterable[str]) -> bool:
    """Whether changes to the files changed, by path, are worth a release: any but lock files',
    counting Go's go.mod as one.

    A package's lock file never reaches the projects that use it, and releasing for one would
    pass each upgrade on down the projects that pin it, and round any that pin each other forever.
    """
    return any(PurePosixPath(path).name not in LOCK_FILES for path in changed)


def locked(ecosystem: Ecosystem, text: str) -> dict[str, str]:
    """What the lock file's text holds each package at, by its name as dependencies.Name has it: a
    version, or for Python and Nix a commit. A Python package or a flake locked from a tag or a
    commit, not a branch, is left out, as no upgrade moves it. A lock file that can't be parsed
    holds nothing."""
    try:
        match ecosystem:
            case Ecosystem.COMPOSER:
                return _composer_locked(json.loads(text))
            case Ecosystem.NPM:
                return _npm_locked(json.loads(text))
            case Ecosystem.PYTHON:
                return _uv_locked(tomllib.loads(text))
            case Ecosystem.GO:
                return dependencies.go_requires(text)
            case Ecosystem.NIX:
                inputs = dependencies.flake_inputs(text)
                return {i.source: i.rev for i in inputs if i.follows_branch}
            case _:
                assert_never(ecosystem)
    except (ValueError, tomllib.TOMLDecodeError):
        return {}


def is_behind(ecosystem: Ecosystem, locked: str, latest: str) -> bool:
    """Whether a package locked at locked is behind latest: a lower version than the latest version
    tag, or for Python and Nix a commit other than the latest, either of them abbreviated."""
    match ecosystem:
        case Ecosystem.COMPOSER | Ecosystem.NPM | Ecosystem.GO:
            return (
                versions.is_version(locked)
                and versions.is_version(latest)
                and versions.key(locked) < versions.key(latest)
            )
        case Ecosystem.PYTHON | Ecosystem.NIX:
            return not (locked.startswith(latest) or latest.startswith(locked))
        case _:
            assert_never(ecosystem)


def upgrade_command(ecosystem: Ecosystem, own_go_modules: Sequence[str]) -> list[str]:
    """The command that upgrades every package in the lock file as far as the manifest's
    constraints allow, and installs nothing: for Go, every module the module's packages and their
    tests need, in go.mod and go.sum. Go asks the repository of each of own_go_modules directly,
    as the module proxy caches the latest version, so can lag a release."""
    match ecosystem:
        case Ecosystem.COMPOSER:
            return ["composer", "update", "--no-interaction", "--no-install", "--no-scripts"]
        case Ecosystem.NPM:
            return ["npm", "update", "--package-lock-only", "--ignore-scripts"]
        case Ecosystem.PYTHON:
            return ["uv", "lock", "--upgrade"]
        case Ecosystem.GO:
            direct = [f"GONOPROXY={','.join(own_go_modules)}"] if own_go_modules else []
            return ["env", *direct, "go", "get", "-u", "-t", "./..."]
        case Ecosystem.NIX:
            return [*dependencies.NIX, "flake", "update"]
        case _:
            assert_never(ecosystem)


def dry_run_copies(ecosystem: Ecosystem) -> tuple[str, ...]:
    """The files a dry run of the upgrade works on copies of, in a scratch directory, for a tool
    that can't say what it would change without changing it: npm's dry run compares with what's
    installed, not with the lock file."""
    match ecosystem:
        case Ecosystem.COMPOSER | Ecosystem.PYTHON | Ecosystem.NIX:
            return ()
        case Ecosystem.NPM:
            return ("package.json", "package-lock.json", ".npmrc")
        case Ecosystem.GO:
            return ("go.mod", "go.sum")
        case _:
            assert_never(ecosystem)


def dry_run_command(
    ecosystem: Ecosystem, own_go_modules: Sequence[str], scratch: Path
) -> list[str]:
    """The upgrade command, changing nothing in the project: writing only to the copies in
    scratch, for an ecosystem with dry_run_copies, or for Nix, to a lock file of its own there."""
    command = upgrade_command(ecosystem, own_go_modules)
    match ecosystem:
        case Ecosystem.COMPOSER | Ecosystem.PYTHON:
            return [*command, "--dry-run"]
        case Ecosystem.NPM:
            return [*command, "--prefix", str(scratch)]
        case Ecosystem.GO:
            at = command.index("get") + 1
            return [*command[:at], f"-modfile={scratch / 'go.mod'}", *command[at:]]
        case Ecosystem.NIX:
            return [*command, "--output-lock-file", str(scratch / lock_file(ecosystem))]
        case _:
            assert_never(ecosystem)


_COMPOSER_CHANGES = ("- Upgrading ", "- Downgrading ", "- Locking ", "- Removing ")
_GO_CHANGES = ("go: upgraded ", "go: downgraded ", "go: added ", "go: removed ")
_UV_CHANGES = ("Update ", "Add ", "Remove ")


def changes(ecosystem: Ecosystem, said: str, before: str, after: str) -> list[str]:
    """Each package an upgrade changed in the lock file, as the tool says so, such as "Update
    ruff v0.1.0 -> v0.2.0": from what the tool said on stderr, or for npm and Nix, which say it
    without the versions, from the lock file's text before and after."""
    lines = [line.strip() for line in said.splitlines()]
    match ecosystem:
        case Ecosystem.COMPOSER:
            return [line[2:] for line in lines if line.startswith(_COMPOSER_CHANGES)]
        case Ecosystem.NPM:
            return _npm_changes(_npm_versions(before), _npm_versions(after))
        case Ecosystem.PYTHON:
            return [line for line in lines if line.startswith(_UV_CHANGES)]
        case Ecosystem.GO:
            return [line.removeprefix("go: ") for line in lines if line.startswith(_GO_CHANGES)]
        case Ecosystem.NIX:
            return _flake_changes(_flake_revs(before), _flake_revs(after))
        case _:
            assert_never(ecosystem)


def install_dir(ecosystem: Ecosystem) -> str | None:
    """Where the project's dependencies are installed, or None for Go and Nix, whose module cache
    and store are shared by every project, and fill as each builds."""
    match ecosystem:
        case Ecosystem.COMPOSER:
            return "vendor"
        case Ecosystem.NPM:
            return "node_modules"
        case Ecosystem.PYTHON:
            return ".venv"
        case Ecosystem.GO | Ecosystem.NIX:
            return None
        case _:
            assert_never(ecosystem)


def install_command(ecosystem: Ecosystem) -> list[str]:
    """The command that installs just what the lock file holds, running the packages' scripts,
    and changes no lock file."""
    match ecosystem:
        case Ecosystem.COMPOSER:
            return ["composer", "install", "--no-interaction"]
        case Ecosystem.NPM:
            return ["npm", "ci"]
        case Ecosystem.PYTHON:
            return ["uv", "sync", "--frozen"]
        case Ecosystem.GO:
            return ["go", "mod", "download"]
        case Ecosystem.NIX:
            return [*dependencies.NIX, "flake", "archive"]
        case _:
            assert_never(ecosystem)


def installed_record(ecosystem: Ecosystem) -> str | None:
    """The file, under install_dir, in which the tool records what it installed, as the lock file
    has it, for an ecosystem whose installs can be compared with the lock file without the tool."""
    match ecosystem:
        case Ecosystem.COMPOSER:
            return "composer/installed.json"
        case Ecosystem.NPM:
            return ".package-lock.json"
        case Ecosystem.PYTHON | Ecosystem.GO | Ecosystem.NIX:
            return None
        case _:
            assert_never(ecosystem)


def installed_behind(ecosystem: Ecosystem, lock: str, record: str) -> bool:
    """Whether what installed_record's text says is installed differs from what the lock file's
    text holds. A package npm locks as optional, as one for another platform is, may be missing.
    Either file failing to parse counts as differing."""
    try:
        match ecosystem:
            case Ecosystem.COMPOSER:
                return _composer_installed(json.loads(record)) != _composer_locked(json.loads(lock))
            case Ecosystem.NPM:
                return _npm_installed_behind(json.loads(lock), json.loads(record))
            case Ecosystem.PYTHON | Ecosystem.GO | Ecosystem.NIX:
                return False
            case _:
                assert_never(ecosystem)
    except ValueError:
        return True


def check_command(ecosystem: Ecosystem) -> list[str] | None:
    """The command that says, by its exit status, whether what's installed differs from the lock
    file, for an ecosystem without an installed_record whose installs can be compared."""
    match ecosystem:
        case Ecosystem.COMPOSER | Ecosystem.NPM | Ecosystem.GO | Ecosystem.NIX:
            return None
        case Ecosystem.PYTHON:
            return ["uv", "sync", "--frozen", "--check"]
        case _:
            assert_never(ecosystem)


def _composer_locked(lock: object) -> dict[str, str]:
    if not isinstance(lock, dict):
        return {}
    return {
        package["name"].lower(): package["version"]
        for section in ("packages", "packages-dev")
        for package in _list(lock.get(section))
        if isinstance(package, dict)
        and isinstance(package.get("name"), str)
        and isinstance(package.get("version"), str)
    }


_NODE_MODULES = "node_modules/"


def _npm_locked(lock: object) -> dict[str, str]:
    if not isinstance(lock, dict):
        return {}
    found: dict[str, str] = {}
    for path, package in _table(lock.get("packages")).items():
        name = path.removeprefix(_NODE_MODULES)
        top_level = path.startswith(_NODE_MODULES) and _NODE_MODULES not in name
        if top_level and isinstance(package, dict) and isinstance(package.get("version"), str):
            found[name] = package["version"]
    return found


def _composer_installed(record: object) -> dict[str, str]:
    """What Composer's installed.json says is installed: a list of packages in Composer 1, or
    under "packages" in Composer 2."""
    packages = record if isinstance(record, list) else _table(record).get("packages")
    return _composer_locked({"packages": packages})


def _npm_versions(text: str) -> dict[str, str]:
    """The version a package-lock.json's text locks each package at, by its path, such as
    node_modules/a/node_modules/b. One that can't be parsed locks nothing."""
    try:
        lock = json.loads(text)
    except ValueError:
        return {}
    return {
        path: package["version"]
        for path, package in _table(_table(lock).get("packages")).items()
        if path.startswith(_NODE_MODULES)
        and isinstance(package, dict)
        and isinstance(package.get("version"), str)
    }


def _npm_changes(before: dict[str, str], after: dict[str, str]) -> list[str]:
    def name(path: str) -> str:
        return path.rpartition(_NODE_MODULES)[2]

    return [
        *(
            f"Update {name(p)} {before[p]} -> {v}"
            for p, v in sorted(after.items())
            if p in before and before[p] != v
        ),
        *(f"Add {name(p)} {v}" for p, v in sorted(after.items()) if p not in before),
        *(f"Remove {name(p)} {v}" for p, v in sorted(before.items()) if p not in after),
    ]


def _npm_installed_behind(lock: object, record: object) -> bool:
    locked = _table(_table(lock).get("packages"))
    installed = _table(_table(record).get("packages"))
    for path, package in locked.items():
        if not path.startswith(_NODE_MODULES) or not isinstance(package, dict):
            continue
        optional = package.get("optional") or package.get("devOptional")
        there = installed.get(path)
        if there is None:
            if not optional:
                return True
        elif not isinstance(there, dict) or there.get("version") != package.get("version"):
            return True
    return any(path.startswith(_NODE_MODULES) and path not in locked for path in installed)


def _flake_revs(text: str) -> dict[str, str]:
    """The commit a flake.lock's text locks each input at, by its node's name, every input's
    inputs too, or "" for one locked at none, as from a path. One that can't be parsed locks
    nothing."""
    try:
        lock = _table(json.loads(text))
    except ValueError:
        return {}
    root = lock.get("root")
    return {
        key: rev if isinstance(rev := _table(node.get("locked")).get("rev"), str) else ""
        for key, node in _table(lock.get("nodes")).items()
        if key != root and isinstance(node, dict)
    }


def _flake_changes(before: dict[str, str], after: dict[str, str]) -> list[str]:
    def at(rev: str) -> str:
        return f" {rev[:7]}" if rev else ""

    return [
        *(
            f"Update {k}{at(before[k])} ->{at(v)}"
            for k, v in sorted(after.items())
            if k in before and before[k] != v
        ),
        *(f"Add {k}{at(v)}" for k, v in sorted(after.items()) if k not in before),
        *(f"Remove {k}{at(v)}" for k, v in sorted(before.items()) if k not in after),
    ]


def _uv_locked(lock: dict) -> dict[str, str]:
    found: dict[str, str] = {}
    for package in _list(lock.get("package")):
        if not isinstance(package, dict) or not isinstance(package.get("name"), str):
            continue
        source = package.get("source")
        url = source.get("git") if isinstance(source, dict) else None
        if not isinstance(url, str):
            continue
        parts = urlsplit(url)
        if parts.fragment and not {"tag", "rev"} & parse_qs(parts.query).keys():
            found[dependencies.normalise(package["name"])] = parts.fragment
    return found


def _table(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list:
    return value if isinstance(value, list) else []
