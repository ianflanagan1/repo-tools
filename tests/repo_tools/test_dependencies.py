import json
import shutil
import subprocess
from pathlib import Path

import pytest

from repo_tools import dependencies
from repo_tools.dependencies import (
    ComposerPackage,
    CopierTemplate,
    Ecosystem,
    FlakeInput,
    GoModule,
    Name,
    NixFlake,
    NpmPackage,
    PythonPackage,
    discover,
    flake_inputs,
    flake_source,
    go_requires,
    icon,
    name_of,
    names,
    offering,
    offers_outputs,
    pinned,
)

NONE_PINNED: frozenset[Name] = frozenset()
NONE_OFFERING: frozenset[Path] = frozenset()


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def test_a_directory_without_a_manifest_is_no_dependency(tmp_path: Path):
    assert discover(tmp_path, NONE_PINNED, NONE_OFFERING) == []


def test_a_composer_json_with_a_name_is_a_composer_package(tmp_path: Path):
    write_json(tmp_path / "composer.json", {"name": "me/thing", "type": "library"})
    assert discover(tmp_path, NONE_PINNED, NONE_OFFERING) == [ComposerPackage("me/thing")]


def test_a_composer_project_is_an_app_not_a_dependency(tmp_path: Path):
    write_json(tmp_path / "composer.json", {"name": "me/app", "type": "project"})
    assert discover(tmp_path, NONE_PINNED, NONE_OFFERING) == []


def test_a_composer_json_without_a_name_is_no_dependency(tmp_path: Path):
    write_json(tmp_path / "composer.json", {"type": "library"})
    assert discover(tmp_path, NONE_PINNED, NONE_OFFERING) == []


def test_a_package_json_with_a_name_is_an_npm_package(tmp_path: Path):
    write_json(tmp_path / "package.json", {"name": "@me/thing"})
    assert discover(tmp_path, NONE_PINNED, NONE_OFFERING) == [NpmPackage("@me/thing")]


def test_a_private_package_json_is_no_dependency(tmp_path: Path):
    write_json(tmp_path / "package.json", {"name": "@me/app", "private": True})
    assert discover(tmp_path, NONE_PINNED, NONE_OFFERING) == []


def test_a_pyproject_another_project_pins_is_a_python_package(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "thing"\n')
    assert discover(tmp_path, {Name(Ecosystem.PYTHON, "thing")}, NONE_OFFERING) == [
        PythonPackage("thing")
    ]


def test_a_python_package_is_pinned_by_its_normalised_name(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "Cli_Kit"\n')
    assert discover(tmp_path, {Name(Ecosystem.PYTHON, "cli-kit")}, NONE_OFFERING) == [
        PythonPackage("Cli_Kit")
    ]


def test_a_pyproject_nothing_pins_is_no_dependency_even_with_a_build_backend(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "tools"\n\n[build-system]\nbuild-backend = "uv_build"\n'
    )
    assert discover(tmp_path, {Name(Ecosystem.NPM, "tools")}, NONE_OFFERING) == []


GO_MOD = """module github.com/me/kit

go 1.27

tool github.com/me/baseline/cmd/baseline

require github.com/me/ports v0.2.0

require (
\tgithub.com/me/baseline v0.4.0 // indirect
\t"github.com/me/quoted" v1.0.0
\tgithub.com/me/local v0.1.0
\tgithub.com/me/sibling v0.1.0
)

replace github.com/me/local => ../local

replace (
\tgithub.com/me/sibling v0.1.0 => ./sibling
\tgithub.com/me/ports => github.com/fork/ports v0.2.1
)
"""


def go_mod(tmp_path: Path, text: str) -> None:
    (tmp_path / "go.mod").write_text(text)


def test_a_go_module_another_project_requires_is_a_go_module_package(tmp_path: Path):
    go_mod(tmp_path, "module github.com/me/kit\n\ngo 1.27\n")
    assert discover(tmp_path, {Name(Ecosystem.GO, "github.com/me/kit")}, NONE_OFFERING) == [
        GoModule("github.com/me/kit")
    ]


def test_a_go_module_nothing_requires_is_no_dependency(tmp_path: Path):
    go_mod(tmp_path, "module github.com/me/app\n")
    assert discover(tmp_path, {Name(Ecosystem.PYTHON, "github.com/me/app")}, NONE_OFFERING) == []


needs_nix = pytest.mark.skipif(shutil.which("nix") is None, reason="needs Nix")

LIB_FLAKE = "{ outputs = { self }: { lib.root = self.outPath; }; }\n"
DEV_FLAKE = "{ outputs = { self }: { devShells = {}; checks = {}; formatter = {}; }; }\n"


def flake_repo(tmp_path: Path, flake: str, *remotes: tuple[str, str]) -> Path:
    """A git repository whose committed flake.nix is flake, with each remote by name and URL."""
    repo = tmp_path / "flake"
    repo.mkdir()
    (repo / "flake.nix").write_text(flake)
    for command in (
        ["init", "--quiet"],
        ["add", "flake.nix"],
        ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "--quiet", "-m", "init"],
        *(["remote", "add", name, url] for name, url in remotes),
    ):
        subprocess.run(["git", "-C", str(repo), *command], check=True, capture_output=True)
    return repo


def test_a_flake_with_an_output_for_other_flakes_is_a_nix_flake_named_by_its_origin(
    tmp_path: Path,
):
    repo = flake_repo(tmp_path, LIB_FLAKE, ("origin", "git@github.com:Me/Kit.git"))
    assert discover(repo, NONE_PINNED, {repo}) == [NixFlake("github.com/me/kit")]


def test_a_flake_without_an_output_for_other_flakes_is_no_dependency(tmp_path: Path):
    repo = flake_repo(tmp_path, DEV_FLAKE, ("origin", "https://github.com/me/app"))
    assert discover(repo, NONE_PINNED, NONE_OFFERING) == []


def test_a_flake_another_project_pins_is_a_nix_flake_whatever_its_outputs(tmp_path: Path):
    repo = flake_repo(tmp_path, DEV_FLAKE, ("origin", "https://github.com/me/app"))
    assert discover(repo, {Name(Ecosystem.NIX, "github.com/me/app")}, NONE_OFFERING) == [
        NixFlake("github.com/me/app")
    ]


def test_a_flake_with_no_remote_yet_is_a_nix_flake_with_no_name(tmp_path: Path):
    repo = flake_repo(tmp_path, LIB_FLAKE)
    assert discover(repo, NONE_PINNED, {repo}) == [NixFlake(None)]


@needs_nix
def test_nix_lists_an_output_other_flakes_can_use(tmp_path: Path):
    assert offers_outputs(flake_repo(tmp_path, LIB_FLAKE))


@needs_nix
def test_nix_lists_none_for_a_flake_with_only_outputs_for_working_on_it_such_as_a_dev_shell(
    tmp_path: Path,
):
    assert not offers_outputs(flake_repo(tmp_path, DEV_FLAKE))


@needs_nix
def test_nix_lists_none_for_a_flake_nix_it_cannot_evaluate(tmp_path: Path):
    assert not offers_outputs(flake_repo(tmp_path, "{ outputs ="))


def test_nothing_is_listed_without_a_flake_or_without_nix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    assert not offers_outputs(tmp_path)
    monkeypatch.setattr(dependencies, "NIX", (str(tmp_path / "no-nix"),))
    assert not offers_outputs(flake_repo(tmp_path, LIB_FLAKE))


@needs_nix
def test_the_projects_offering_outputs_are_those_nix_lists_one_for(tmp_path: Path):
    lib, dev = tmp_path / "lib", tmp_path / "dev"
    lib.mkdir()
    dev.mkdir()
    lib_repo, dev_repo = flake_repo(lib, LIB_FLAKE), flake_repo(dev, DEV_FLAKE)
    assert offering([lib_repo, dev_repo, tmp_path]) == {lib_repo}


def test_a_copier_yml_is_a_copier_template(tmp_path: Path):
    (tmp_path / "copier.yml").write_text("_subdirectory: template\n")
    assert discover(tmp_path, NONE_PINNED, NONE_OFFERING) == [CopierTemplate()]


def test_a_copier_yaml_is_a_copier_template_too(tmp_path: Path):
    (tmp_path / "copier.yaml").write_text("_subdirectory: template\n")
    assert discover(tmp_path, NONE_PINNED, NONE_OFFERING) == [CopierTemplate()]


def test_a_repository_can_be_several_kinds_of_dependency_in_a_fixed_order(tmp_path: Path):
    (tmp_path / "copier.yml").write_text("")
    write_json(tmp_path / "package.json", {"name": "thing"})
    write_json(tmp_path / "composer.json", {"name": "me/thing"})
    assert discover(tmp_path, NONE_PINNED, NONE_OFFERING) == [
        ComposerPackage("me/thing"),
        NpmPackage("thing"),
        CopierTemplate(),
    ]


def test_a_manifest_it_cannot_parse_is_no_dependency(tmp_path: Path):
    (tmp_path / "composer.json").write_text("not json")
    (tmp_path / "package.json").write_text("[]")
    (tmp_path / "pyproject.toml").write_text("[project")
    assert discover(tmp_path, NONE_PINNED, NONE_OFFERING) == []


# --- What a project is called, and what it pins


def test_a_project_is_called_by_the_name_in_each_of_its_manifests(tmp_path: Path):
    write_json(tmp_path / "composer.json", {"name": "Me/Thing", "type": "project"})
    write_json(tmp_path / "package.json", {"name": "@me/thing", "private": True})
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "My.Thing"\n')
    go_mod(tmp_path, "module github.com/me/thing // the module\n")
    assert names(tmp_path) == {
        Name(Ecosystem.COMPOSER, "me/thing"),
        Name(Ecosystem.NPM, "@me/thing"),
        Name(Ecosystem.PYTHON, "my-thing"),
        Name(Ecosystem.GO, "github.com/me/thing"),
    }


def test_a_directory_without_a_manifest_is_called_nothing_and_pins_nothing(tmp_path: Path):
    assert (names(tmp_path), pinned(tmp_path)) == (set(), set())


def test_a_flake_is_called_by_where_its_origin_fetches_from(tmp_path: Path):
    repo = flake_repo(
        tmp_path, LIB_FLAKE, ("fork", "https://example.com/x"), ("origin", "/srv/git/kit.git")
    )
    assert names(repo) == {Name(Ecosystem.NIX, "/srv/git/kit")}


def test_a_flake_with_one_remote_not_called_origin_is_called_by_where_that_fetches_from(
    tmp_path: Path,
):
    repo = flake_repo(tmp_path, LIB_FLAKE, ("upstream", "https://github.com/me/kit.git"))
    assert names(repo) == {Name(Ecosystem.NIX, "github.com/me/kit")}


def test_a_flake_with_no_remote_is_called_nothing(tmp_path: Path):
    assert names(flake_repo(tmp_path, LIB_FLAKE)) == set()


@pytest.mark.parametrize(
    "url",
    [
        "git@github.com:Me/Kit.git",
        "ssh://git@github.com/me/kit",
        "https://github.com/me/kit.git",
        "git+https://github.com/me/kit/",
        "git+ssh://git@GitHub.com/me/kit.git",
    ],
)
def test_a_remote_s_url_in_any_form_fetches_from_its_host_and_path(url: str):
    assert flake_source(url) == "github.com/me/kit"


def test_a_repository_on_this_machine_fetches_from_its_path_as_it_is():
    assert flake_source("git+file:///Users/Me/kit.git?ref=main") == "/Users/Me/kit"
    assert flake_source("/Users/Me/My%20kit") == "/Users/Me/My%20kit"
    assert flake_source("file:///Users/Me/My%20kit") == "/Users/Me/My kit"


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


def test_each_go_requirement_is_pinned_unless_replaced_by_a_local_path(tmp_path: Path):
    go_mod(tmp_path, GO_MOD)
    assert pinned(tmp_path) == {
        Name(Ecosystem.GO, f"github.com/me/{n}") for n in ("ports", "baseline", "quoted")
    }


def flake_lock(**inputs: dict) -> str:
    """A flake.lock whose root has each input, by name, as the node given: or as a follows path,
    for a list."""
    nodes = {name: node for name, node in inputs.items() if isinstance(node, dict)}
    nodes["indirect-dep"] = {"original": {"type": "github", "owner": "me", "repo": "transitive"}}
    root = {
        "inputs": {name: node if isinstance(node, list) else name for name, node in inputs.items()}
    }
    return json.dumps({"nodes": {**nodes, "root": root}, "root": "root", "version": 7})


def node(original: dict, rev: str = "abc123") -> dict:
    return {"original": original, "locked": {**original, "rev": rev}}


FLAKE_LOCK = flake_lock(
    kit=node({"type": "github", "owner": "Me", "repo": "Kit"}),
    rules=node({"type": "git", "url": "ssh://git@example.com/me/rules.git"}, "def456"),
    tools=node({"type": "gitlab", "owner": "me", "repo": "tools", "ref": "v1.2.0"}),
    base=node({"type": "github", "owner": "me", "repo": "base", "rev": "0a1b2c"}, "0a1b2c"),
    here=node({"type": "path", "path": "/Users/me/here"}),
    nixpkgs=node({"type": "indirect", "id": "nixpkgs"}),
    shared=["kit", "shared"],
)


def test_each_input_of_a_flake_lock_from_git_is_pinned_but_not_from_a_path_or_the_registry(
    tmp_path: Path,
):
    (tmp_path / "flake.lock").write_text(FLAKE_LOCK)
    assert pinned(tmp_path) == {
        Name(Ecosystem.NIX, source)
        for source in ("github.com/me/kit", "example.com/me/rules", "gitlab.com/me/tools")
    } | {Name(Ecosystem.NIX, "github.com/me/base")}


def test_a_flake_lock_holds_each_input_from_git_at_its_commit_and_says_if_it_follows_a_branch():
    assert flake_inputs(FLAKE_LOCK) == [
        FlakeInput("github.com/me/kit", "abc123", follows_branch=True),
        FlakeInput("example.com/me/rules", "def456", follows_branch=True),
        FlakeInput("gitlab.com/me/tools", "abc123", follows_branch=False),
        FlakeInput("github.com/me/base", "0a1b2c", follows_branch=False),
    ]


def test_a_flake_lock_that_cannot_be_parsed_holds_nothing():
    assert flake_inputs("not json") == []
    assert flake_inputs("[]") == []


def test_a_go_mod_requires_each_module_at_its_version():
    assert go_requires(GO_MOD) == {
        "github.com/me/ports": "v0.2.0",
        "github.com/me/baseline": "v0.4.0",
        "github.com/me/quoted": "v1.0.0",
        "github.com/me/local": "v0.1.0",
        "github.com/me/sibling": "v0.1.0",
    }


@pytest.mark.parametrize(
    ("dependency", "expected"),
    [
        (ComposerPackage("me/thing"), "🐘"),
        (NpmPackage("thing"), "🔴"),
        (PythonPackage("thing"), "🐍"),
        (GoModule("example.com/thing"), "🐹"),
        (CopierTemplate(), "📋"),
        (NixFlake("github.com/me/kit"), "⛄"),
    ],
)
def test_each_kind_of_dependency_has_its_icon(dependency, expected):
    assert icon(dependency) == expected


def test_a_dependency_is_named_as_the_projects_that_pin_it_name_it():
    assert name_of(ComposerPackage("Me/Thing")) == Name(Ecosystem.COMPOSER, "me/thing")
    assert name_of(NpmPackage("@me/thing")) == Name(Ecosystem.NPM, "@me/thing")
    assert name_of(PythonPackage("My_Kit")) == Name(Ecosystem.PYTHON, "my-kit")
    assert name_of(GoModule("github.com/Me/Kit")) == Name(Ecosystem.GO, "github.com/Me/Kit")
    assert name_of(NixFlake("github.com/me/kit")) == Name(Ecosystem.NIX, "github.com/me/kit")


def test_a_kind_of_dependency_nothing_pins_has_no_such_name():
    assert name_of(CopierTemplate()) is None
    assert name_of(NixFlake(None)) is None
