"""Behaviour of what each ecosystem takes to release a package, upgrade a lock file and install
what it holds."""

import argparse
import json
from pathlib import Path

import pytest

from repo_list import ecosystems
from repo_list.config import Config
from repo_tools.dependencies import Ecosystem, Name


def parsed(*argv: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    ecosystems.add_flags(parser, lambda e: "", "")
    return parser.parse_args(argv)


# --- Flags


def test_each_ecosystem_has_a_flag_of_its_own():
    long_flags = [ecosystems.flags(e)[-1] for e in Ecosystem]
    assert len(set(long_flags)) == len(Ecosystem)


def test_the_dependencies_flag_chooses_every_ecosystem():
    assert ecosystems.chosen(parsed("--dependencies")) == set(Ecosystem)


def test_an_ecosystem_s_flag_chooses_just_that_ecosystem():
    assert ecosystems.chosen(parsed("--npm")) == {Ecosystem.NPM}


def test_the_packagist_flag_chooses_composer():
    assert ecosystems.chosen(parsed("--packagist")) == {Ecosystem.COMPOSER}


def test_no_flag_chooses_no_ecosystem():
    assert ecosystems.chosen(parsed()) == set()


# --- Settings


def test_composer_and_npm_need_the_vendor_and_scope_they_are_judged_by():
    settings = Config()
    assert ecosystems.missing_setting(Ecosystem.COMPOSER, settings) == (
        "packagist.vendor",
        "your vendor name",
    )
    assert ecosystems.missing_setting(Ecosystem.NPM, settings) == ("npm.scope", "your scope")


@pytest.mark.parametrize("ecosystem", [Ecosystem.PYTHON, Ecosystem.GO, Ecosystem.NIX])
def test_python_go_and_nix_need_no_setting(ecosystem):
    assert ecosystems.missing_setting(ecosystem, Config()) is None


# --- Whose package it is


def test_a_composer_package_is_yours_when_it_is_your_vendor_s_whatever_the_case():
    settings = Config(packagist_vendor="Me")
    assert ecosystems.is_yours(Name(Ecosystem.COMPOSER, "me/a"), settings)
    assert not ecosystems.is_yours(Name(Ecosystem.COMPOSER, "someone/a"), settings)


def test_an_npm_package_is_yours_when_it_is_in_your_scope():
    settings = Config(npm_scope="@me")
    assert ecosystems.is_yours(Name(Ecosystem.NPM, "@me/a"), settings)
    assert not ecosystems.is_yours(Name(Ecosystem.NPM, "@meet/a"), settings)


def test_a_python_package_is_yours_as_one_of_your_repositories_pins_it():
    assert ecosystems.is_yours(Name(Ecosystem.PYTHON, "kit"), Config())


def test_a_go_module_is_yours_as_one_of_your_repositories_requires_it():
    assert ecosystems.is_yours(Name(Ecosystem.GO, "github.com/me/kit"), Config())


def test_a_flake_is_yours_as_it_is_one_of_your_repositories():
    assert ecosystems.is_yours(Name(Ecosystem.NIX, "github.com/me/kit"), Config())


# --- Releasing


def test_composer_npm_and_go_packages_are_released_by_version_tag_but_python_and_nix_not():
    assert {e for e in Ecosystem if ecosystems.releases_by_tag(e)} == {
        Ecosystem.COMPOSER,
        Ecosystem.NPM,
        Ecosystem.GO,
    }


def test_changes_to_more_than_lock_files_are_released():
    assert ecosystems.needs_release(["composer.lock", "src/a.php"])


@pytest.mark.parametrize(
    "lock_file", ["composer.lock", "package-lock.json", "uv.lock", "go.mod", "go.sum", "flake.lock"]
)
def test_changes_to_lock_files_alone_are_not_released(lock_file):
    assert not ecosystems.needs_release([lock_file, f"tools/{lock_file}"])


def test_a_go_upgrade_changes_go_mod_and_go_sum_and_its_versions_are_in_go_mod():
    assert ecosystems.lock_files(Ecosystem.GO) == ("go.mod", "go.sum")
    assert ecosystems.lock_file(Ecosystem.GO) == "go.mod"


def test_no_changes_are_not_released():
    assert not ecosystems.needs_release([])


# --- What a lock file holds


def test_a_composer_lock_holds_each_package_and_dev_package_at_its_version_by_lowercased_name():
    lock = {
        "packages": [{"name": "Me/A", "version": "v1.0.0"}],
        "packages-dev": [{"name": "me/b", "version": "2.1.0"}],
    }
    assert ecosystems.locked(Ecosystem.COMPOSER, json.dumps(lock)) == {
        "me/a": "v1.0.0",
        "me/b": "2.1.0",
    }


def test_a_package_lock_holds_each_top_level_package_at_its_version():
    lock = {
        "lockfileVersion": 3,
        "packages": {
            "": {"name": "app"},
            "node_modules/@me/a": {"version": "1.0.0"},
            "node_modules/@me/a/node_modules/b": {"version": "3.0.0"},
        },
    }
    assert ecosystems.locked(Ecosystem.NPM, json.dumps(lock)) == {"@me/a": "1.0.0"}


UV_LOCK = """version = 1

[[package]]
name = "My_Kit"
version = "0.1.0"
source = { git = "https://github.com/me/kit?branch=main#0123abc" }

[[package]]
name = "pinned"
version = "0.1.0"
source = { git = "https://github.com/me/pinned?tag=v0.1.0#4567def" }

[[package]]
name = "ruff"
version = "0.6.0"
source = { registry = "https://pypi.org/simple" }
"""


def test_a_uv_lock_holds_each_package_from_a_git_branch_at_its_commit_by_normalised_name():
    assert ecosystems.locked(Ecosystem.PYTHON, UV_LOCK) == {"my-kit": "0123abc"}


def test_a_go_mod_holds_each_requirement_at_its_version():
    go_mod = "module github.com/me/app\n\nrequire (\n\tgithub.com/me/kit v0.2.0 // indirect\n)\n"
    assert ecosystems.locked(Ecosystem.GO, go_mod) == {"github.com/me/kit": "v0.2.0"}


def node(original: dict, rev: str) -> dict:
    return {"original": original, "locked": {**original, "rev": rev}}


def flake_lock(**nodes: dict) -> str:
    root = {"inputs": {name: name for name in nodes}}
    return json.dumps({"nodes": {**nodes, "root": root}, "root": "root", "version": 7})


def test_a_flake_lock_holds_each_input_following_a_git_branch_at_its_commit_by_its_source():
    lock = flake_lock(
        kit=node({"type": "github", "owner": "me", "repo": "kit"}, "0123abcdef"),
        pinned=node({"type": "github", "owner": "me", "repo": "pinned", "ref": "v1.0.0"}, "4567"),
        here=node({"type": "path", "path": "/Users/me/here"}, "89ab"),
    )
    assert ecosystems.locked(Ecosystem.NIX, lock) == {"github.com/me/kit": "0123abcdef"}


@pytest.mark.parametrize("ecosystem", list(Ecosystem))
def test_a_lock_file_that_cannot_be_parsed_holds_nothing(ecosystem):
    assert ecosystems.locked(ecosystem, "{not a lock") == {}


# --- Behind


@pytest.mark.parametrize("ecosystem", [Ecosystem.COMPOSER, Ecosystem.NPM, Ecosystem.GO])
def test_a_version_below_the_latest_tag_is_behind_whether_or_not_either_has_a_v(ecosystem):
    assert ecosystems.is_behind(ecosystem, "1.0.0", "v1.0.1")
    assert not ecosystems.is_behind(ecosystem, "v1.0.1", "1.0.1")
    assert not ecosystems.is_behind(ecosystem, "1.1.0", "v1.0.1")


def test_a_version_that_is_not_one_such_as_a_branch_is_never_behind():
    assert not ecosystems.is_behind(Ecosystem.COMPOSER, "dev-main", "v1.0.1")


def test_a_go_pseudo_version_is_never_behind():
    assert not ecosystems.is_behind(Ecosystem.GO, "v0.0.0-20261010193011-f71dc92da45e", "v0.1.0")


@pytest.mark.parametrize("ecosystem", [Ecosystem.PYTHON, Ecosystem.NIX])
def test_a_commit_other_than_the_latest_is_behind(ecosystem):
    assert ecosystems.is_behind(ecosystem, "0123abc", "89abcdef0123")
    assert not ecosystems.is_behind(ecosystem, "0123abc", "0123abcdef01")


# --- Upgrading


def test_each_ecosystem_upgrades_every_package_in_its_lock_file_and_installs_nothing():
    assert ecosystems.upgrade_command(Ecosystem.COMPOSER, []) == [
        "composer",
        "update",
        "--no-interaction",
        "--no-install",
        "--no-scripts",
    ]
    assert ecosystems.upgrade_command(Ecosystem.NPM, []) == [
        "npm",
        "update",
        "--package-lock-only",
        "--ignore-scripts",
    ]
    assert ecosystems.upgrade_command(Ecosystem.PYTHON, []) == ["uv", "lock", "--upgrade"]
    assert ecosystems.upgrade_command(Ecosystem.GO, []) == [
        "env",
        "go",
        "get",
        "-u",
        "-t",
        "./...",
    ]
    assert ecosystems.upgrade_command(Ecosystem.NIX, []) == [
        "nix",
        "--extra-experimental-features",
        "nix-command flakes",
        "flake",
        "update",
    ]


def test_nix_runs_as_the_machine_s_own_and_every_other_tool_from_the_project_s_devbox():
    assert {e for e in Ecosystem if not ecosystems.runs_in_devbox(e)} == {Ecosystem.NIX}


def test_a_go_upgrade_asks_the_repositories_of_your_modules_directly_not_the_proxy():
    command = ecosystems.upgrade_command(Ecosystem.GO, ["github.com/me/a", "github.com/me/b"])
    assert command[:2] == ["env", "GONOPROXY=github.com/me/a,github.com/me/b"]


def test_nix_dry_runs_the_upgrade_by_writing_the_lock_file_it_would_to_scratch():
    command = ecosystems.dry_run_command(Ecosystem.NIX, [], Path("/scratch"))
    assert command == [
        *ecosystems.upgrade_command(Ecosystem.NIX, []),
        "--output-lock-file",
        "/scratch/flake.lock",
    ]
    assert ecosystems.dry_run_copies(Ecosystem.NIX) == ()


def test_the_changes_to_a_flake_lock_are_read_from_it_before_and_after_by_input():
    github = {"type": "github", "owner": "me", "repo": "kit"}
    before = flake_lock(
        kit=node(github, "0123abcdef"),
        gone=node({"type": "git", "url": "https://example.com/gone"}, "4567abcdef"),
    )
    after = flake_lock(kit=node(github, "89abcdef01"), new=node({"type": "path", "path": "/x"}, ""))
    assert ecosystems.changes(Ecosystem.NIX, "• Updated input 'kit'", before, after) == [
        "Update kit 0123abc -> 89abcde",
        "Add new",
        "Remove gone 4567abc",
    ]


def test_composer_and_uv_dry_run_the_upgrade_themselves():
    for ecosystem in (Ecosystem.COMPOSER, Ecosystem.PYTHON):
        command = ecosystems.dry_run_command(ecosystem, [], Path("/scratch"))
        assert command == [*ecosystems.upgrade_command(ecosystem, []), "--dry-run"]
        assert ecosystems.dry_run_copies(ecosystem) == ()


def test_npm_dry_runs_the_upgrade_on_copies_of_its_manifest_and_lock_file():
    assert ecosystems.dry_run_command(Ecosystem.NPM, [], Path("/scratch"))[-2:] == [
        "--prefix",
        "/scratch",
    ]
    assert ecosystems.dry_run_copies(Ecosystem.NPM) == (
        "package.json",
        "package-lock.json",
        ".npmrc",
    )


def test_go_dry_runs_the_upgrade_on_copies_of_go_mod_and_go_sum():
    command = ecosystems.dry_run_command(Ecosystem.GO, ["github.com/me/a"], Path("/scratch"))
    assert command == [
        "env",
        "GONOPROXY=github.com/me/a",
        "go",
        "get",
        "-modfile=/scratch/go.mod",
        "-u",
        "-t",
        "./...",
    ]
    assert ecosystems.dry_run_copies(Ecosystem.GO) == ("go.mod", "go.sum")


UV_SAID = """Resolved 17 packages in 667ms
Update pluggy v1.6.0 -> v1.7.0
Add tomli v2.2.1
Remove colorama v0.4.6
"""


def test_the_changes_to_a_uv_lock_are_the_packages_uv_says_it_updates_adds_and_removes():
    assert ecosystems.changes(Ecosystem.PYTHON, UV_SAID, "", "") == [
        "Update pluggy v1.6.0 -> v1.7.0",
        "Add tomli v2.2.1",
        "Remove colorama v0.4.6",
    ]


def test_a_lock_that_is_already_up_to_date_has_no_changes():
    assert ecosystems.changes(Ecosystem.PYTHON, "Resolved 17 packages in 2ms\n", "", "") == []
    composer = "Updating dependencies\nNothing to modify in lock file\n"
    assert ecosystems.changes(Ecosystem.COMPOSER, composer, "", "") == []


COMPOSER_SAID = """Loading composer repositories with package information
Updating dependencies
Lock file operations: 1 install, 2 updates, 1 removal
  - Locking psr/clock (1.0.0)
  - Upgrading psr/log (1.0.0 => 1.1.4)
  - Downgrading me/kit (v2.0.0 => v1.9.0)
  - Removing psr/old (1.0.0)
Writing lock file
"""


def test_the_changes_to_a_composer_lock_are_the_lock_file_operations_composer_lists():
    assert ecosystems.changes(Ecosystem.COMPOSER, COMPOSER_SAID, "", "") == [
        "Locking psr/clock (1.0.0)",
        "Upgrading psr/log (1.0.0 => 1.1.4)",
        "Downgrading me/kit (v2.0.0 => v1.9.0)",
        "Removing psr/old (1.0.0)",
    ]


GO_SAID = """go: downloading golang.org/x/text v0.43.0
go: upgraded go 1.22 => 1.26.0
go: upgraded golang.org/x/text v0.20.0 => v0.43.0
go: added golang.org/x/sync v0.1.0
"""


def test_the_changes_to_a_go_mod_are_what_go_get_says_it_upgraded_and_added():
    assert ecosystems.changes(Ecosystem.GO, GO_SAID, "", "") == [
        "upgraded go 1.22 => 1.26.0",
        "upgraded golang.org/x/text v0.20.0 => v0.43.0",
        "added golang.org/x/sync v0.1.0",
    ]


def package_lock(**versions: str) -> str:
    packages = {"": {"name": "app"}} | {
        f"node_modules/{path}": {"version": v} for path, v in versions.items()
    }
    return json.dumps({"lockfileVersion": 3, "packages": packages})


def test_the_changes_to_a_package_lock_are_read_from_it_before_and_after_as_npm_lists_none():
    before = package_lock(ms="2.0.0", old="1.0.0")
    after = package_lock(ms="2.1.3", new="1.0.0")
    assert ecosystems.changes(Ecosystem.NPM, "up to date", before, after) == [
        "Update ms 2.0.0 -> 2.1.3",
        "Add new 1.0.0",
        "Remove old 1.0.0",
    ]


def test_a_nested_package_s_change_is_named_by_the_package():
    before = json.dumps({"packages": {"node_modules/a/node_modules/b": {"version": "1.0.0"}}})
    after = json.dumps({"packages": {"node_modules/a/node_modules/b": {"version": "1.0.1"}}})
    assert ecosystems.changes(Ecosystem.NPM, "", before, after) == ["Update b 1.0.0 -> 1.0.1"]


# --- Installing


def test_each_ecosystem_installs_what_its_lock_file_holds_without_changing_it():
    assert ecosystems.install_command(Ecosystem.COMPOSER) == [
        "composer",
        "install",
        "--no-interaction",
    ]
    assert ecosystems.install_command(Ecosystem.NPM) == ["npm", "ci"]
    assert ecosystems.install_command(Ecosystem.PYTHON) == ["uv", "sync", "--frozen"]
    assert ecosystems.install_command(Ecosystem.GO) == ["go", "mod", "download"]
    assert ecosystems.install_command(Ecosystem.NIX)[-2:] == ["flake", "archive"]


@pytest.mark.parametrize("ecosystem", [Ecosystem.GO, Ecosystem.NIX])
def test_go_and_nix_install_into_a_shared_store_so_have_nothing_of_their_own_to_fall_behind(
    ecosystem,
):
    assert ecosystems.install_dir(ecosystem) is None


def installed_json(**versions: str) -> str:
    packages = [{"name": n, "version": v} for n, v in versions.items()]
    return json.dumps({"packages": packages, "dev": True, "dev-package-names": []})


def composer_lock(**versions: str) -> str:
    return json.dumps({"packages": [{"name": n, "version": v} for n, v in versions.items()]})


def test_composer_s_installs_are_behind_when_a_version_differs_from_the_lock_file():
    lock = composer_lock(**{"psr/log": "1.1.4"})
    assert not ecosystems.installed_behind(
        Ecosystem.COMPOSER, lock, installed_json(**{"psr/log": "1.1.4"})
    )
    assert ecosystems.installed_behind(
        Ecosystem.COMPOSER, lock, installed_json(**{"psr/log": "1.0.0"})
    )
    assert ecosystems.installed_behind(Ecosystem.COMPOSER, lock, installed_json())


def test_composer_1_s_list_of_installed_packages_is_read_too():
    lock = composer_lock(**{"psr/log": "1.1.4"})
    record = json.dumps([{"name": "psr/log", "version": "1.1.4"}])
    assert not ecosystems.installed_behind(Ecosystem.COMPOSER, lock, record)


def test_npm_s_installs_are_behind_when_a_package_differs_is_missing_or_is_extra():
    lock = package_lock(ms="2.1.3")
    assert not ecosystems.installed_behind(Ecosystem.NPM, lock, package_lock(ms="2.1.3"))
    assert ecosystems.installed_behind(Ecosystem.NPM, lock, package_lock(ms="2.0.0"))
    assert ecosystems.installed_behind(Ecosystem.NPM, lock, package_lock())
    assert ecosystems.installed_behind(Ecosystem.NPM, lock, package_lock(ms="2.1.3", x="1"))


def test_an_optional_npm_package_such_as_one_for_another_platform_may_be_missing():
    lock = json.dumps(
        {
            "packages": {
                "node_modules/ms": {"version": "2.1.3"},
                "node_modules/@esbuild/linux-x64": {"version": "0.1.0", "optional": True},
                "node_modules/fsevents": {"version": "2.3.3", "devOptional": True},
            }
        }
    )
    assert not ecosystems.installed_behind(Ecosystem.NPM, lock, package_lock(ms="2.1.3"))


def test_a_record_of_what_is_installed_that_cannot_be_parsed_is_behind():
    assert ecosystems.installed_behind(Ecosystem.NPM, package_lock(), "not json")


def test_uv_says_itself_whether_what_is_installed_is_behind():
    assert ecosystems.installed_record(Ecosystem.PYTHON) is None
    assert ecosystems.check_command(Ecosystem.PYTHON) == ["uv", "sync", "--frozen", "--check"]
