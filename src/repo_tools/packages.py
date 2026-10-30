"""Which kinds of package a project is, read from its manifests, for repo-list to show and for
repo-fix and the publishing commands to act on.

Each kind is told by its own ecosystem's marker, so an app stays out by saying so in its manifest,
as it already does to stop an accidental publish:

    composer.json                 Composer   a name, and a type other than project
    package.json                  npm        a name, and not "private": true
    pyproject.toml                Python     a name another project pins
    go.mod                        Go         a module path another project pins
    .claude-plugin/plugin.json    Claude     a name
    copier.yml or copier.yaml     Copier     the file

Python has no marker that tells a library from a tool: both have a build backend to be installed.
Nor has Go one that tells a library from a command. So a Python project or a Go module is a
package once another project pins it, as below.

A project can be several kinds at once. A manifest that can't be parsed counts as none.
Whose package it is, such as your Packagist vendor's, is for whoever acts on it to judge.

A project pins a dependency when its lock file holds the dependency at a version or commit, so a
new one reaches it only by updating the lock; not when it reads one from a path, which it sees as
it is on disk:

    composer.json                 require and require-dev, unless composer.lock reads it from a path
    package.json                  dependencies, dev, optional and peer, unless file:, link:,
                                  workspace:, portal: or a path
    pyproject.toml                dependencies, optional ones and dependency groups, from a git
                                  source in tool.uv.sources, or named with a git+ URL
    go.mod                        require, unless a replace directive reads it from a path

Package is a closed family: what differs by kind belongs in functions that match on it, such as
icon, so a new kind fails the type check until each has a case for it.
"""

import json
import re
import tomllib
from collections.abc import Iterator, Set
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import assert_never, final


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
class ClaudePlugin:
    """A Claude Code plugin, installed from a marketplace."""

    name: str


@final
@dataclass(frozen=True)
class CopierTemplate:
    """A Copier template, which the projects made from it update from with `copier update`."""


type Package = (
    ComposerPackage | NpmPackage | PythonPackage | GoModule | ClaudePlugin | CopierTemplate
)


class Ecosystem(Enum):
    """Where a dependency is named, and so which names it could be."""

    COMPOSER = "composer"
    NPM = "npm"
    PYTHON = "python"
    GO = "go"


@final
@dataclass(frozen=True)
class Name:
    """A project's name in an ecosystem, as dependants name it: Composer's lowercased, Python's
    normalised as pip compares them."""

    ecosystem: Ecosystem
    name: str


def discover(project: Path, pinned_by_others: Set[Name]) -> list[Package]:
    """Every kind of package the project is, in the order of the table above, given every name
    other projects pin."""
    found: list[Package | None] = [
        _composer(project),
        _npm(project),
        _python(project, pinned_by_others),
        _go(project, pinned_by_others),
        _claude_plugin(project),
        _copier(project),
    ]
    return [package for package in found if package is not None]


def icon(package: Package) -> str:
    """The icon repo-list shows for the kind, from Unicode 11 or earlier, the widths VS Code's
    terminal knows."""
    match package:
        case ComposerPackage():
            return "🐘"
        case NpmPackage():
            return "🔴"
        case PythonPackage():
            return "🐍"
        case GoModule():
            return "🐹"
        case ClaudePlugin():
            return "🧩"
        case CopierTemplate():
            return "📋"
        case _:
            assert_never(package)


def name_of(package: Package) -> Name | None:
    """The package's name as the projects that pin it name it, or None for a kind nothing pins."""
    match package:
        case ComposerPackage(name):
            return Name(Ecosystem.COMPOSER, name.lower())
        case NpmPackage(name):
            return Name(Ecosystem.NPM, name)
        case PythonPackage(name):
            return Name(Ecosystem.PYTHON, normalise(name))
        case GoModule(name):
            return Name(Ecosystem.GO, name)
        case ClaudePlugin() | CopierTemplate():
            return None
        case _:
            assert_never(package)


def names(project: Path) -> set[Name]:
    """What the project is called in each ecosystem it has a manifest for, whether or not it's a
    package there."""
    composer = _name(_json(project / "composer.json"))
    npm = _name(_json(project / "package.json"))
    python = _name(_toml(project / "pyproject.toml").get("project"))
    go = _go_mod(project).module
    return {
        *([Name(Ecosystem.COMPOSER, composer.lower())] if composer else []),
        *([Name(Ecosystem.NPM, npm)] if npm else []),
        *([Name(Ecosystem.PYTHON, normalise(python))] if python else []),
        *([Name(Ecosystem.GO, go)] if go else []),
    }


def pinned(project: Path) -> set[Name]:
    """Each dependency the project pins, as the table above says."""
    return {
        *_composer_pinned(project),
        *_npm_pinned(project),
        *_python_pinned(project),
        *_go_pinned(project),
    }


def go_requires(text: str) -> dict[str, str]:
    """The version the go.mod's text requires each module at, by its path."""
    return _parse_go_mod(text).requires


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


def _claude_plugin(project: Path) -> ClaudePlugin | None:
    name = _name(_json(project / ".claude-plugin" / "plugin.json"))
    return ClaudePlugin(name) if name else None


def _copier(project: Path) -> CopierTemplate | None:
    if (project / "copier.yml").is_file() or (project / "copier.yaml").is_file():
        return CopierTemplate()
    return None


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
