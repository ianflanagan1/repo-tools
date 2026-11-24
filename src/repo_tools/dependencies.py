"""Which kinds of dependency a project is for other projects, read from its manifests, for
repo-list to show and for repo-fix and the publishing commands to act on.

Each kind is told by its own ecosystem's marker, so an app stays out by saying so in its manifest,
as it already does to stop an accidental publish:

    composer.json                 Composer   a name, and a type other than project
    package.json                  npm        a name, and not "private": true
    pyproject.toml                Python     a name another project pins
    go.mod                        Go         a module path another project pins
    copier.yml or copier.yaml     Copier     the file
    flake.nix                     Nix        an output for other flakes, or another project pins it

Python has no marker that tells a library from a tool: both have a build backend to be installed.
Nor has Go one that tells a library from a command. So a Python project or a Go module is a
dependency once another project pins it, as below.

A flake is a dependency once it has an output other flakes can use, such as lib or packages, and
not only those for working on it: a dev shell, checks, a formatter or CI jobs. Asking Nix takes
tens of milliseconds, so whoever discovers dependencies asks once for each project, with offering,
and passes on the projects whose flakes have one. Nix lists the outputs without evaluating them or
fetching anything, from the files git tracks. A flake Nix can't list, as when Nix isn't installed,
is a dependency only once another project pins it. A flake has no name of its own: the projects
that pin it name it by where they fetch it from, as flake_source has it, so it's named by where
its remote is.

A project can be several kinds at once. A manifest that can't be parsed counts as none.
Whose dependency it is, such as your Packagist vendor's, is for whoever acts on it to judge.

A project pins a dependency when its lock file holds the dependency at a version or commit, so a
new one reaches it only by updating the lock; not when it reads one from a path, which it sees as
it is on disk:

    composer.json                 require and require-dev, unless composer.lock reads it from a path
    package.json                  dependencies, dev, optional and peer, unless file:, link:,
                                  workspace:, portal: or a path
    pyproject.toml                dependencies, optional ones and dependency groups, from a git
                                  source in tool.uv.sources, or named with a git+ URL
    go.mod                        require, unless a replace directive reads it from a path
    flake.lock                    the root's inputs, from git, GitHub, GitLab or SourceHut; not
                                  from a path, a tarball or the flake registry

Dependency is a closed family: what differs by kind belongs in functions that match on it, such as
icon, so a new kind fails the type check until each has a case for it.
"""

import json
import os
import re
import subprocess
import tomllib
from collections.abc import Iterable, Iterator, Set
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import assert_never, final
from urllib.parse import unquote, urlsplit

from repo_tools import versions

NIX = ("nix", "--extra-experimental-features", "nix-command flakes")
"""Nix, with flakes, whether or not its config turns them on."""


@final
@dataclass(frozen=True)
class ComposerPackage:
    name: str


@final
@dataclass(frozen=True)
class NpmPackage:
    name: str


@final
@dataclass(frozen=True)
class PythonPackage:
    name: str


@final
@dataclass(frozen=True)
class GoModule:
    name: str
    """The module path, such as github.com/me/kit."""


@final
@dataclass(frozen=True)
class CopierTemplate:
    """A Copier template, which the projects made from it update from with `copier update`."""


@final
@dataclass(frozen=True)
class NixFlake:
    name: str | None
    """Where the flakes that pin it fetch it from, such as github.com/me/kit, or None for one with
    no remote yet."""


type Dependency = (
    ComposerPackage | NpmPackage | PythonPackage | GoModule | CopierTemplate | NixFlake
)


class Ecosystem(Enum):
    """Where a dependency is named, and so which names it could be."""

    COMPOSER = "composer"
    NPM = "npm"
    PYTHON = "python"
    GO = "go"
    NIX = "nix"


@final
@dataclass(frozen=True)
class Name:
    """A project's name in an ecosystem, as dependants name it: Composer's lowercased, Python's
    normalised as pip compares them."""

    ecosystem: Ecosystem
    name: str


def discover(project: Path, pinned_by_others: Set[Name], offering: Set[Path]) -> list[Dependency]:
    """Every kind of dependency the project is, in the order of the table above, given every name
    other projects pin, and every project whose flake has an output for other flakes."""
    found: list[Dependency | None] = [
        _composer(project),
        _npm(project),
        _python(project, pinned_by_others),
        _go(project, pinned_by_others),
        _copier(project),
        _flake(project, pinned_by_others, offering),
    ]
    return [d for d in found if d is not None]


def icon(dependency: Dependency) -> str:
    """The icon repo-list shows for the kind, from Unicode 11 or earlier, the widths VS Code's
    terminal knows."""
    match dependency:
        case ComposerPackage():
            return "🐘"
        case NpmPackage():
            return "🔴"
        case PythonPackage():
            return "🐍"
        case GoModule():
            return "🐹"
        case CopierTemplate():
            return "📋"
        case NixFlake():
            return "⛄"
        case _:
            assert_never(dependency)


def name_of(dependency: Dependency) -> Name | None:
    """The dependency's name as the projects that pin it name it, or None for a kind nothing
    pins."""
    match dependency:
        case ComposerPackage(name):
            return Name(Ecosystem.COMPOSER, name.lower())
        case NpmPackage(name):
            return Name(Ecosystem.NPM, name)
        case PythonPackage(name):
            return Name(Ecosystem.PYTHON, normalise(name))
        case GoModule(name):
            return Name(Ecosystem.GO, name)
        case NixFlake(name):
            return Name(Ecosystem.NIX, name) if name else None
        case CopierTemplate():
            return None
        case _:
            assert_never(dependency)


def names(project: Path) -> set[Name]:
    """What the project is called in each ecosystem it has a manifest for, whether or not it's a
    dependency there."""
    composer = _name(_json(project / "composer.json"))
    npm = _name(_json(project / "package.json"))
    python = _name(_toml(project / "pyproject.toml").get("project"))
    go = _go_mod(project).module
    nix = _flake_name(project)
    return {
        *([Name(Ecosystem.COMPOSER, composer.lower())] if composer else []),
        *([Name(Ecosystem.NPM, npm)] if npm else []),
        *([Name(Ecosystem.PYTHON, normalise(python))] if python else []),
        *([Name(Ecosystem.GO, go)] if go else []),
        *([Name(Ecosystem.NIX, nix)] if nix else []),
    }


def pinned(project: Path) -> set[Name]:
    """Each dependency the project pins, as the table above says."""
    return {
        *_composer_pinned(project),
        *_npm_pinned(project),
        *_python_pinned(project),
        *_go_pinned(project),
        *_nix_pinned(project),
    }


def go_requires(text: str) -> dict[str, str]:
    """The version the go.mod's text requires each module at, by its path."""
    return _parse_go_mod(text).requires


@final
@dataclass(frozen=True)
class FlakeInput:
    source: str
    """Where it's fetched from, as flake_source has it."""
    rev: str
    """The commit it's locked at."""
    follows_branch: bool
    """Whether an update can move it: not when its flake.nix names a commit or a version tag."""


def flake_inputs(text: str) -> list[FlakeInput]:
    """Each input of the flake.lock's root fetched from git, in its order: not one from a path, a
    tarball or the flake registry, nor one that follows another input's. A lock file that can't be
    parsed holds none."""
    try:
        lock = _table(json.loads(text))
    except ValueError:
        return []
    nodes = _table(lock.get("nodes"))
    root = _table(nodes.get(lock.get("root")))
    found = []
    for key in _table(root.get("inputs")).values():
        node = _table(nodes.get(key)) if isinstance(key, str) else {}
        original = _table(node.get("original"))
        source = _git_source(original)
        rev = _table(node.get("locked")).get("rev")
        if source and isinstance(rev, str):
            ref = original.get("ref")
            tag = isinstance(ref, str) and versions.is_version(ref.removeprefix("refs/tags/"))
            found.append(FlakeInput(source, rev, "rev" not in original and not tag))
    return found


def flake_source(url: str) -> str:
    """Where a git URL fetches from, named alike by a remote and by the flakes that pin it: a
    remote's host and path in any form, lowercased, or the path of a repository on this machine,
    as it is; either without a trailing .git."""
    url = url.removeprefix("git+")
    if url.startswith("file://"):
        where = unquote(urlsplit(url).path)
    elif url.startswith("/"):
        where = url
    elif "://" in url:
        parts = urlsplit(url)
        where = f"{parts.hostname}{parts.path}".lower()
    elif match := re.fullmatch(r"(?:[^@/]+@)?([^/:]+):/?(.*)", url):
        where = f"{match[1]}/{match[2]}".lower()
    else:
        where = url
    return where.rstrip("/").removesuffix(".git")


def _composer(project: Path) -> ComposerPackage | None:
    composer = _json(project / "composer.json")
    if composer.get("type") == "project":
        return None
    name = _name(composer)
    return ComposerPackage(name) if name else None


def _npm(project: Path) -> NpmPackage | None:
    manifest = _json(project / "package.json")
    if manifest.get("private") is True:
        return None
    name = _name(manifest)
    return NpmPackage(name) if name else None


def _python(project: Path, pinned_by_others: Set[Name]) -> PythonPackage | None:
    name = _name(_toml(project / "pyproject.toml").get("project"))
    if name and Name(Ecosystem.PYTHON, normalise(name)) in pinned_by_others:
        return PythonPackage(name)
    return None


def _go(project: Path, pinned_by_others: Set[Name]) -> GoModule | None:
    module = _go_mod(project).module
    if module and Name(Ecosystem.GO, module) in pinned_by_others:
        return GoModule(module)
    return None


def _copier(project: Path) -> CopierTemplate | None:
    if (project / "copier.yml").is_file() or (project / "copier.yaml").is_file():
        return CopierTemplate()
    return None


def offering(projects: Iterable[Path]) -> set[Path]:
    """The projects whose flakes have an output for other flakes, as Nix lists them."""
    return {project for project in projects if offers_outputs(project)}


def _flake(project: Path, pinned_by_others: Set[Name], offering: Set[Path]) -> NixFlake | None:
    if not (project / "flake.nix").is_file():
        return None
    name = _flake_name(project)
    if (name and Name(Ecosystem.NIX, name) in pinned_by_others) or project in offering:
        return NixFlake(name)
    return None


def _flake_name(project: Path) -> str | None:
    """Where a flake's remote is: its origin, or with none, its only remote."""
    if not (project / "flake.nix").is_file():
        return None
    remotes = _git(project, "remote").split()
    remote = "origin" if "origin" in remotes else remotes[0] if len(remotes) == 1 else None
    url = _git(project, "remote", "get-url", remote) if remote else ""
    return flake_source(url) if url else None


_FLAKE_ENV = "REPO_TOOLS_FLAKE"
_OUTPUTS = f'builtins.attrNames (builtins.getFlake (builtins.getEnv "{_FLAKE_ENV}")).outputs'
_FOR_WORKING_ON_IT = frozenset({"checks", "devShell", "devShells", "formatter", "hydraJobs"})


def offers_outputs(project: Path) -> bool:
    """Whether the project has a flake, and Nix lists an output of it that other flakes can use.
    It runs nothing the flake builds, and fetches nothing."""
    if not (project / "flake.nix").is_file():
        return False
    command = [
        *NIX,
        "eval",
        "--json",
        "--offline",
        "--impure",
        "--option",
        "allow-import-from-derivation",
        "false",
        "--expr",
        _OUTPUTS,
    ]
    env = {**os.environ, _FLAKE_ENV: f"git+{project.absolute().as_uri()}"}
    try:
        result = subprocess.run(command, capture_output=True, text=True, env=env)
        outputs = json.loads(result.stdout) if result.returncode == 0 else []
    except (OSError, ValueError):
        return False
    return any(o not in _FOR_WORKING_ON_IT for o in _list(outputs) if isinstance(o, str))


def _git(project: Path, *args: str) -> str:
    """What git wrote, or "" if it failed."""
    result = subprocess.run(["git", "-C", str(project), *args], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ""


_PATH_SPECS = ("file:", "link:", "workspace:", "portal:", ".", "/", "~")
_REQUIREMENT = re.compile(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)[^@;]*(@\s*git\+)?")


def _composer_pinned(project: Path) -> Iterator[Name]:
    composer = _json(project / "composer.json")
    lock = _json(project / "composer.lock")
    from_path = {
        locked["name"].lower()
        for section in ("packages", "packages-dev")
        for locked in _list(lock.get(section))
        if isinstance(locked, dict)
        and isinstance(locked.get("name"), str)
        and _dig(locked, "dist", "type") == "path"
    }
    for section in ("require", "require-dev"):
        for name in _table(composer.get(section)):
            if name.lower() not in from_path:
                yield Name(Ecosystem.COMPOSER, name.lower())


def _npm_pinned(project: Path) -> Iterator[Name]:
    manifest = _json(project / "package.json")
    for section in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
        for name, spec in _table(manifest.get(section)).items():
            if isinstance(spec, str) and not spec.startswith(_PATH_SPECS):
                yield Name(Ecosystem.NPM, name)


def _python_pinned(project: Path) -> Iterator[Name]:
    pyproject = _toml(project / "pyproject.toml")
    from_git = {
        normalise(name)
        for name, source in _table(_dig(pyproject, "tool", "uv", "sources")).items()
        if any(isinstance(s, dict) and "git" in s for s in _list(source) or [source])
    }
    for requirement in _requirements(pyproject):
        if match := _REQUIREMENT.match(requirement):
            name = normalise(match[1])
            if match[2] or name in from_git:
                yield Name(Ecosystem.PYTHON, name)


def _go_pinned(project: Path) -> Iterator[Name]:
    go_mod = _go_mod(project)
    for module in go_mod.requires:
        if module not in go_mod.from_path:
            yield Name(Ecosystem.GO, module)


def _nix_pinned(project: Path) -> Iterator[Name]:
    try:
        text = (project / "flake.lock").read_text()
    except OSError:
        return
    for flake_input in flake_inputs(text):
        yield Name(Ecosystem.NIX, flake_input.source)


def _git_source(original: dict) -> str | None:
    """Where a flake.lock's original reference fetches from, for one from git."""
    owner, repo, host = original.get("owner"), original.get("repo"), original.get("host")
    match original.get("type"):
        case "github" | "gitlab" | "sourcehut" as git_host if owner and repo:
            default = {"github": "github.com", "gitlab": "gitlab.com", "sourcehut": "git.sr.ht"}
            return f"{host or default[git_host]}/{owner}/{repo}".lower()
        case "git" if isinstance(url := original.get("url"), str):
            return flake_source(url)
        case _:
            return None


@final
@dataclass(frozen=True)
class _GoMod:
    module: str | None
    requires: dict[str, str]
    """The version each module is required at, by its path."""
    from_path: frozenset[str]
    """Each module a replace directive reads from a path on disk."""


_GO_PATH_PREFIXES = ("./", "../", "/")


def _go_mod(project: Path) -> _GoMod:
    try:
        return _parse_go_mod((project / "go.mod").read_text())
    except OSError:
        return _parse_go_mod("")


def _parse_go_mod(text: str) -> _GoMod:
    """The module, requirements and path replacements in a go.mod's text, from directives on one
    line or in a block. Lines it can't read are skipped."""
    module = None
    requires: dict[str, str] = {}
    from_path: set[str] = set()
    block = None
    for line in text.splitlines():
        words = [w.strip('"`') for w in line.split("//", 1)[0].split()]
        if block is not None and words == [")"]:
            block = None
            continue
        if block is not None:
            verb, args = block, words
        elif words[1:] == ["("]:
            block = words[0]
            continue
        else:
            verb, args = (words[0], words[1:]) if words else ("", [])
        match verb, args:
            case "module", [path]:
                module = path
            case "require", [path, version]:
                requires[path] = version
            case "replace", [path, *_, "=>", target] | [path, *_, "=>", target, _]:
                if target.startswith(_GO_PATH_PREFIXES):
                    from_path.add(path)
            case _:
                pass
    return _GoMod(module, requires, frozenset(from_path))


def _requirements(pyproject: dict) -> Iterator[str]:
    """Every requirement the pyproject names: its dependencies, optional ones and dependency
    groups, leaving out a group's include-group tables."""
    lists = [
        _dig(pyproject, "project", "dependencies"),
        *_table(_dig(pyproject, "project", "optional-dependencies")).values(),
        *_table(pyproject.get("dependency-groups")).values(),
    ]
    for requirements in lists:
        yield from (r for r in _list(requirements) if isinstance(r, str))


def normalise(name: str) -> str:
    """A Python project's name as pip compares them."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _table(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list:
    return value if isinstance(value, list) else []


def _json(path: Path) -> dict:
    """The object in the JSON file, or {} when there's none or it isn't an object."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _toml(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def _dig(data: object, *keys: str) -> object:
    """The value at keys in nested tables, or None where one isn't there or isn't a table."""
    for key in keys:
        data = data.get(key) if isinstance(data, dict) else None
    return data


def _name(manifest: object) -> str | None:
    name = manifest.get("name") if isinstance(manifest, dict) else None
    return name if isinstance(name, str) and name else None
