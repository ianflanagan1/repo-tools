"""Each ecosystem a package of yours can be in, such as Composer, and what it takes there to
release the package and upgrade the projects that pin it.

Ecosystem is a closed family: each function here matches on it, so a new one fails the type
check until each has a case for it. The flags that choose ecosystems are made from it too, so a
new one gets a flag of its own and is among those --packages chooses.
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
from repo_tools import packages, versions
from repo_tools.packages import Ecosystem, Name

PACKAGES = "--packages"


def flags(ecosystem: Ecosystem) -> tuple[str, ...]:
    """The flag that chooses the ecosystem, its long form last."""
    match ecosystem:
        case Ecosystem.COMPOSER:
            return ("-p", "--packagist")
        case Ecosystem.NPM:
            return ("--npm",)
        case Ecosystem.PYTHON:
            return ("--python",)
        case Ecosystem.GO:
            return ("--go",)
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
        case _:
            assert_never(ecosystem)


def add_flags(
    parser: argparse.ArgumentParser, help: Callable[[Ecosystem], str], every: str
) -> None:
    """Adds a flag for each ecosystem, with help(ecosystem) as its help, then --packages, which
    chooses them all, with every as its help."""
    for ecosystem in Ecosystem:
        parser.add_argument(
            *flags(ecosystem), dest=ecosystem.value, action="store_true", help=help(ecosystem)
        )
    parser.add_argument(PACKAGES, action="store_true", help=every)


def chosen(args: argparse.Namespace) -> frozenset[Ecosystem]:
    """The ecosystems the flags add_flags added choose."""
    return frozenset(e for e in Ecosystem if args.packages or getattr(args, e.value))


def missing_setting(ecosystem: Ecosystem, settings: Config) -> tuple[str, str] | None:
    """The setting in config.toml the ecosystem needs to judge which packages are yours, and what
    it is, when settings lack it."""
    match ecosystem:
        case Ecosystem.COMPOSER:
            return None if settings.packagist_vendor else ("packagist.vendor", "your vendor name")
        case Ecosystem.NPM:
            return None if settings.npm_scope else ("npm.scope", "your scope")
        case Ecosystem.PYTHON | Ecosystem.GO:
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
    project or Go module is a package only once another of the repositories here pins it, any."""
    match name.ecosystem:
        case Ecosystem.COMPOSER:
            vendor = settings.packagist_vendor
            return vendor is not None and name.name.startswith(f"{vendor.lower()}/")
        case Ecosystem.NPM:
            scope = settings.npm_scope
            return scope is not None and name.name.startswith(f"{scope}/")
        case Ecosystem.PYTHON | Ecosystem.GO:
            return True
        case _:
            assert_never(name.ecosystem)


def yours(
    project: Path, ecosystems: Set[Ecosystem], settings: Config, pinned: Set[Name]
) -> set[Name]:
    """The names of the packages of yours the project is, in the ecosystems chosen, given every
    name the projects here pin."""
    found = (packages.name_of(p) for p in packages.discover(project, pinned))
    return {
        name
        for name in found
        if name is not None and name.ecosystem in ecosystems and is_yours(name, settings)
    }


def providers(
    projects: Iterable[Path], ecosystems: Set[Ecosystem], settings: Config, pinned: Set[Name]
) -> dict[Name, Path]:
    """The project each package of yours in the ecosystems chosen comes from, by its name: the
    first, where several are the same package, as a repository's worktrees are."""
    found: dict[Name, Path] = {}
    for project in projects:
        for name in yours(project, ecosystems, settings, pinned):
            found.setdefault(name, project)
    return found


def releases_by_tag(ecosystem: Ecosystem) -> bool:
    """Whether a new version of a package reaches the projects that pin it by a version tag, or
    else, as a Python package pinned from git, by its commit alone."""
    match ecosystem:
        case Ecosystem.COMPOSER | Ecosystem.NPM | Ecosystem.GO:
            return True
        case Ecosystem.PYTHON:
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
        case _:
            assert_never(ecosystem)


def lock_file(ecosystem: Ecosystem) -> str:
    """The file that holds the version of each package."""
    return lock_files(ecosystem)[0]


def tool(ecosystem: Ecosystem) -> str:
    """The command that upgrades the ecosystem's lock file."""
    match ecosystem:
        case Ecosystem.COMPOSER:
            return "composer"
        case Ecosystem.NPM:
            return "npm"
        case Ecosystem.PYTHON:
            return "uv"
        case Ecosystem.GO:
            return "go"
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
    """What the lock file's text holds each package at, by its name as packages.Name has it: a
    version, or for Python a commit. A Python package locked from a tag or a commit, not a
    branch, is left out, as no upgrade moves it. A lock file that can't be parsed holds nothing."""
    try:
        match ecosystem:
            case Ecosystem.COMPOSER:
                return _composer_locked(json.loads(text))
            case Ecosystem.NPM:
                return _npm_locked(json.loads(text))
            case Ecosystem.PYTHON:
                return _uv_locked(tomllib.loads(text))
            case Ecosystem.GO:
                return packages.go_requires(text)
            case _:
                assert_never(ecosystem)
    except (ValueError, tomllib.TOMLDecodeError):
        return {}


def is_behind(ecosystem: Ecosystem, locked: str, latest: str) -> bool:
    """Whether a package locked at locked is behind latest: a lower version than the latest version
    tag, or for Python a commit other than the latest, either of them abbreviated."""
    match ecosystem:
        case Ecosystem.COMPOSER | Ecosystem.NPM | Ecosystem.GO:
            return (
                versions.is_version(locked)
                and versions.is_version(latest)
                and versions.key(locked) < versions.key(latest)
            )
        case Ecosystem.PYTHON:
            return not (locked.startswith(latest) or latest.startswith(locked))
        case _:
            assert_never(ecosystem)


def upgrade_command(ecosystem: Ecosystem, names: Sequence[str]) -> list[str]:
    """The command that upgrades just the packages named in the lock file, and touches nothing
    else: no manifest but Go's go.mod, and nothing installed. Go asks each module's repository for
    its latest version tag directly, as the module proxy caches @latest, so can lag a release."""
    match ecosystem:
        case Ecosystem.COMPOSER:
            return [
                "composer",
                "update",
                "--no-interaction",
                "--no-install",
                "--no-scripts",
                *names,
            ]
        case Ecosystem.NPM:
            return ["npm", "update", "--package-lock-only", *names]
        case Ecosystem.PYTHON:
            return ["uv", "lock", *(arg for name in names for arg in ("--upgrade-package", name))]
        case Ecosystem.GO:
            return ["env", "GOPROXY=direct", "go", "get", *(f"{name}@latest" for name in names)]
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
            found[packages.normalise(package["name"])] = parts.fragment
    return found


def _table(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list:
    return value if isinstance(value, list) else []
