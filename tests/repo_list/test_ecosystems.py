"""Behaviour of what each ecosystem a package is in takes to release it and upgrade its
dependants."""

import argparse
import json

import pytest

from repo_list import ecosystems
from repo_list.config import Config
from repo_tools.packages import Ecosystem, Name


def parsed(*argv: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    ecosystems.add_flags(parser, lambda e: "", "")
    return parser.parse_args(argv)


# --- Flags


def test_each_ecosystem_has_a_flag_of_its_own():
    long_flags = [ecosystems.flags(e)[-1] for e in Ecosystem]
    assert len(set(long_flags)) == len(Ecosystem)


def test_the_packages_flag_chooses_every_ecosystem():
    assert ecosystems.chosen(parsed("--packages")) == set(Ecosystem)


def test_an_ecosystem_s_flag_chooses_just_that_ecosystem():
    assert ecosystems.chosen(parsed("--npm")) == {Ecosystem.NPM}


def test_the_packagist_flag_chooses_composer_and_keeps_its_short_form():
    assert ecosystems.chosen(parsed("-p")) == {Ecosystem.COMPOSER}


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


@pytest.mark.parametrize("ecosystem", [Ecosystem.PYTHON, Ecosystem.GO])
def test_python_and_go_need_no_setting(ecosystem):
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


# --- Releasing


def test_composer_npm_and_go_packages_are_released_by_version_tag_but_python_ones_are_not():
    assert {e for e in Ecosystem if ecosystems.releases_by_tag(e)} == {
        Ecosystem.COMPOSER,
        Ecosystem.NPM,
        Ecosystem.GO,
    }


def test_changes_to_more_than_lock_files_are_released():
    assert ecosystems.needs_release(["composer.lock", "src/a.php"])


@pytest.mark.parametrize(
    "lock_file", ["composer.lock", "package-lock.json", "uv.lock", "go.mod", "go.sum"]
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


def test_a_commit_other_than_the_latest_is_behind():
    assert ecosystems.is_behind(Ecosystem.PYTHON, "0123abc", "89abcdef0123")
    assert not ecosystems.is_behind(Ecosystem.PYTHON, "0123abc", "0123abcdef01")


# --- Upgrading


def test_each_ecosystem_upgrades_just_the_named_packages_and_only_in_its_lock_file():
    names = ["a", "b"]
    assert ecosystems.upgrade_command(Ecosystem.COMPOSER, names) == [
        "composer",
        "update",
        "--no-interaction",
        "--no-install",
        "--no-scripts",
        "a",
        "b",
    ]
    assert ecosystems.upgrade_command(Ecosystem.NPM, names) == [
        "npm",
        "update",
        "--package-lock-only",
        "a",
        "b",
    ]
    assert ecosystems.upgrade_command(Ecosystem.PYTHON, names) == [
        "uv",
        "lock",
        "--upgrade-package",
        "a",
        "--upgrade-package",
        "b",
    ]
    assert ecosystems.upgrade_command(Ecosystem.GO, names) == [
        "env",
        "GOPROXY=direct",
        "go",
        "get",
        "a@latest",
        "b@latest",
    ]
