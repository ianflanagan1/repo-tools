"""What a project's package manifests say: its one-line description, and its Composer package
name.

The description is read from its package manifest.

Manifests are tried in this order, and the first with a non-empty description wins:

    composer.json    description                  PHP
    package.json     description                  JavaScript
    Cargo.toml       package.description          Rust (or workspace.package.description)
    pyproject.toml   project.description          Python (or tool.poetry.description)
    pom.xml          project > description        Java (Maven)
    *.csproj         PropertyGroup > Description  .NET
    *.gemspec        summary                      Ruby

A manifest that can't be parsed counts as having no description.
"""

import json
import re
import tomllib
from collections.abc import Iterator
from pathlib import Path
from xml.etree import ElementTree

GEMSPEC_SUMMARY = re.compile(r"""^\s*[a-z_]+\.summary\s*=\s*["'](.*)["']\s*$""", re.MULTILINE)


def description(project: Path) -> str:
    """Returns the project's description, or "" when no manifest has one."""
    for candidate in _candidates(project):
        for line in candidate.splitlines():
            if line:
                return line
    return ""


def _candidates(project: Path) -> Iterator[str]:
    yield _from_json(project / "composer.json")
    yield _from_json(project / "package.json")
    cargo = _toml(project / "Cargo.toml")
    yield _dig(cargo, "package", "description")
    yield _dig(cargo, "workspace", "package", "description")
    pyproject = _toml(project / "pyproject.toml")
    yield _dig(pyproject, "project", "description")
    yield _dig(pyproject, "tool", "poetry", "description")
    yield _from_xml(project / "pom.xml", "description", top_level=True)
    for csproj in sorted(project.glob("*.csproj")):
        yield _from_xml(csproj, "Description", top_level=False)
    for gemspec in sorted(project.glob("*.gemspec")):
        match = GEMSPEC_SUMMARY.search(gemspec.read_text(errors="replace"))
        yield match.group(1) if match else ""


def _from_json(path: Path) -> str:
    try:
        value = json.loads(path.read_text()).get("description")
    except (OSError, ValueError, AttributeError):
        return ""
    return value if isinstance(value, str) else ""


def _toml(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def _dig(data: dict, *keys: str) -> str:
    for key in keys:
        if not isinstance(data, dict):
            return ""
        data = data.get(key)
    return data if isinstance(data, str) else ""


def _from_xml(path: Path, tag: str, *, top_level: bool) -> str:
    """The text of the first <tag> element, ignoring XML namespaces.

    top_level: only a direct child of the root element counts, as for pom.xml, where nested
    elements such as a dependency's <description> belong to something else.
    """
    try:
        root = ElementTree.parse(path).getroot()
    except (OSError, ElementTree.ParseError):
        return ""
    elements = root if top_level else root.iter()
    for element in elements:
        if element.tag.rpartition("}")[2] == tag:
            return (element.text or "").strip()
    return ""


def composer_name(project: Path) -> str | None:
    """The package name in the project's composer.json, or None when it has none."""
    try:
        name = json.loads((project / "composer.json").read_text()).get("name")
    except (OSError, ValueError, AttributeError):
        return None
    return name if isinstance(name, str) and name else None
