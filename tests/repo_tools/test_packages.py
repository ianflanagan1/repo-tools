import json
from pathlib import Path

import pytest

from repo_tools.packages import (
    ClaudePlugin,
    ComposerPackage,
    CopierTemplate,
    Ecosystem,
    Name,
    NpmPackage,
    PythonPackage,
    discover,
    icon,
    names,
    pinned,
)

NONE_PINNED: frozenset[Name] = frozenset()


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def test_a_directory_without_a_manifest_is_no_package(tmp_path: Path):
    assert discover(tmp_path, NONE_PINNED) == []


def test_a_composer_json_with_a_name_is_a_composer_package(tmp_path: Path):
    write_json(tmp_path / "composer.json", {"name": "me/thing", "type": "library"})
    assert discover(tmp_path, NONE_PINNED) == [ComposerPackage("me/thing")]


def test_a_composer_project_is_an_app_not_a_package(tmp_path: Path):
    write_json(tmp_path / "composer.json", {"name": "me/app", "type": "project"})
    assert discover(tmp_path, NONE_PINNED) == []


def test_a_composer_json_without_a_name_is_no_package(tmp_path: Path):
    write_json(tmp_path / "composer.json", {"type": "library"})
    assert discover(tmp_path, NONE_PINNED) == []


def test_a_package_json_with_a_name_is_an_npm_package(tmp_path: Path):
    write_json(tmp_path / "package.json", {"name": "@me/thing"})
    assert discover(tmp_path, NONE_PINNED) == [NpmPackage("@me/thing")]


def test_a_private_package_json_is_no_package(tmp_path: Path):
    write_json(tmp_path / "package.json", {"name": "@me/app", "private": True})
    assert discover(tmp_path, NONE_PINNED) == []


def test_a_pyproject_another_project_pins_is_a_python_package(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "thing"\n')
    assert discover(tmp_path, {Name(Ecosystem.PYTHON, "thing")}) == [PythonPackage("thing")]


def test_a_python_package_is_pinned_by_its_normalised_name(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "Cli_Kit"\n')
    assert discover(tmp_path, {Name(Ecosystem.PYTHON, "cli-kit")}) == [PythonPackage("Cli_Kit")]


def test_a_pyproject_nothing_pins_is_no_package_even_with_a_build_backend(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "tools"\n\n[build-system]\nbuild-backend = "uv_build"\n'
    )
    assert discover(tmp_path, {Name(Ecosystem.NPM, "tools")}) == []


def test_a_claude_plugin_manifest_is_a_claude_plugin(tmp_path: Path):
    write_json(tmp_path / ".claude-plugin" / "plugin.json", {"name": "static-checks"})
    assert discover(tmp_path, NONE_PINNED) == [ClaudePlugin("static-checks")]


def test_a_copier_yml_is_a_copier_template(tmp_path: Path):
    (tmp_path / "copier.yml").write_text("_subdirectory: template\n")
    assert discover(tmp_path, NONE_PINNED) == [CopierTemplate()]


def test_a_copier_yaml_is_a_copier_template_too(tmp_path: Path):
    (tmp_path / "copier.yaml").write_text("_subdirectory: template\n")
    assert discover(tmp_path, NONE_PINNED) == [CopierTemplate()]


def test_a_repository_can_be_several_kinds_of_package_in_a_fixed_order(tmp_path: Path):
    (tmp_path / "copier.yml").write_text("")
    write_json(tmp_path / "package.json", {"name": "thing"})
    write_json(tmp_path / "composer.json", {"name": "me/thing"})
    assert discover(tmp_path, NONE_PINNED) == [
        ComposerPackage("me/thing"),
        NpmPackage("thing"),
        CopierTemplate(),
    ]


def test_a_manifest_it_cannot_parse_is_no_package(tmp_path: Path):
    (tmp_path / "composer.json").write_text("not json")
    (tmp_path / "package.json").write_text("[]")
    (tmp_path / "pyproject.toml").write_text("[project")
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / ".claude-plugin" / "plugin.json").write_text("{")
    assert discover(tmp_path, NONE_PINNED) == []


# --- What a project is called, and what it pins


def test_a_project_is_called_by_the_name_in_each_of_its_manifests(tmp_path: Path):
    write_json(tmp_path / "composer.json", {"name": "Me/Thing", "type": "project"})
    write_json(tmp_path / "package.json", {"name": "@me/thing", "private": True})
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "My.Thing"\n')
    assert names(tmp_path) == {
        Name(Ecosystem.COMPOSER, "me/thing"),
        Name(Ecosystem.NPM, "@me/thing"),
        Name(Ecosystem.PYTHON, "my-thing"),
    }


def test_a_directory_without_a_manifest_is_called_nothing_and_pins_nothing(tmp_path: Path):
    assert (names(tmp_path), pinned(tmp_path)) == (set(), set())


def pyproject(tmp_path: Path, text: str) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "app"\n' + text)


def test_a_python_dependency_from_a_git_source_is_pinned(tmp_path: Path):
    pyproject(
        tmp_path,
        'dependencies = ["cli-kit"]\n\n[tool.uv.sources]\n'
        'cli-kit = { git = "https://github.com/me/cli-kit", branch = "main" }\n',
    )
    assert pinned(tmp_path) == {Name(Ecosystem.PYTHON, "cli-kit")}


def test_a_python_dependency_with_any_of_its_sources_from_git_is_pinned(tmp_path: Path):
    pyproject(
        tmp_path,
        'dependencies = ["Cli_Kit>=0.1"]\n\n[tool.uv.sources]\ncli-kit = [\n'
        '  { path = "../cli-kit", marker = "sys_platform == \'darwin\'" },\n'
        '  { git = "https://github.com/me/cli-kit", marker = "sys_platform == \'linux\'" },\n'
        "]\n",
    )
    assert pinned(tmp_path) == {Name(Ecosystem.PYTHON, "cli-kit")}


def test_a_python_dependency_named_with_a_git_url_is_pinned(tmp_path: Path):
    pyproject(tmp_path, 'dependencies = ["cli-kit @ git+https://github.com/me/cli-kit@main"]\n')
    assert pinned(tmp_path) == {Name(Ecosystem.PYTHON, "cli-kit")}


def test_a_python_dependency_read_from_a_path_is_not_pinned(tmp_path: Path):
    pyproject(
        tmp_path,
        'dependencies = ["a", "b"]\n\n[tool.uv.sources]\n'
        'a = { path = "../a", editable = true }\nb = { path = "../b" }\n',
    )
    assert pinned(tmp_path) == set()


def test_a_python_dependency_from_the_registry_is_not_pinned(tmp_path: Path):
    pyproject(tmp_path, 'dependencies = ["requests>=2"]\n')
    assert pinned(tmp_path) == set()


def test_optional_python_dependencies_and_dependency_groups_are_pinned_too(tmp_path: Path):
    pyproject(
        tmp_path,
        '\n[project.optional-dependencies]\nextra = ["a"]\n\n'
        '[dependency-groups]\ndev = ["b", { include-group = "extra" }]\n\n'
        '[tool.uv.sources]\na = { git = "https://example.com/a" }\n'
        'b = { git = "https://example.com/b" }\n',
    )
    assert pinned(tmp_path) == {Name(Ecosystem.PYTHON, "a"), Name(Ecosystem.PYTHON, "b")}


def test_composer_requirements_and_dev_requirements_are_pinned(tmp_path: Path):
    write_json(
        tmp_path / "composer.json",
        {"require": {"Me/A": "^1"}, "require-dev": {"me/b": "dev-main"}},
    )
    assert pinned(tmp_path) == {Name(Ecosystem.COMPOSER, "me/a"), Name(Ecosystem.COMPOSER, "me/b")}


def test_a_composer_requirement_its_lock_reads_from_a_path_is_not_pinned(tmp_path: Path):
    write_json(tmp_path / "composer.json", {"require": {"me/a": "*", "me/b": "*"}})
    write_json(
        tmp_path / "composer.lock",
        {
            "packages": [{"name": "me/a", "dist": {"type": "path", "url": "../a"}}],
            "packages-dev": [{"name": "me/b", "dist": {"type": "zip"}}],
        },
    )
    assert pinned(tmp_path) == {Name(Ecosystem.COMPOSER, "me/b")}


def test_npm_dependencies_from_the_registry_or_git_are_pinned(tmp_path: Path):
    write_json(
        tmp_path / "package.json",
        {
            "dependencies": {"@me/a": "^1.0.0"},
            "devDependencies": {"@me/b": "github:me/b"},
            "optionalDependencies": {"@me/c": "git+https://example.com/c.git"},
            "peerDependencies": {"@me/d": "*"},
        },
    )
    assert pinned(tmp_path) == {Name(Ecosystem.NPM, f"@me/{n}") for n in "abcd"}


@pytest.mark.parametrize("spec", ["file:../a", "link:../a", "workspace:*", "portal:../a", "../a"])
def test_an_npm_dependency_read_from_a_path_is_not_pinned(tmp_path: Path, spec: str):
    write_json(tmp_path / "package.json", {"dependencies": {"@me/a": spec}})
    assert pinned(tmp_path) == set()


@pytest.mark.parametrize(
    ("package", "expected"),
    [
        (ComposerPackage("me/thing"), "🐘"),
        (NpmPackage("thing"), "🔴"),
        (PythonPackage("thing"), "🐍"),
        (ClaudePlugin("thing"), "🧩"),
        (CopierTemplate(), "📋"),
    ],
)
def test_each_kind_of_package_has_its_icon(package, expected):
    assert icon(package) == expected
