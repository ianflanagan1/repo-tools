"""github rename from start to finish, with GitHub and Packagist replaced by fakes."""

import subprocess
from pathlib import Path

import pytest
from cli_kit import outcome
from cli_kit.outcome import Done, NothingToDo, Precondition

from repo_tools.github import api as github
from repo_tools.github.commands.rename import rename
from repo_tools.packagist import api as packagist


def git(directory: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(directory), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


class Services:
    """GitHub's repos, each name leading to a repo's current name, as GitHub redirects an old
    name; and the repository URL of each package Packagist has."""

    def __init__(self) -> None:
        self.names = {"me/old": "me/old"}
        self.packagist: dict[str, str] = {}

    def rename(self, repo: str, new_name: str) -> None:
        new = f"{repo.split('/')[0]}/{new_name}"
        self.names = {name: new if to == repo else to for name, to in self.names.items()}
        self.names[new] = new


@pytest.fixture
def services(monkeypatch: pytest.MonkeyPatch) -> Services:
    services = Services()
    monkeypatch.setattr(github, "current_name", lambda repo: services.names.get(repo))
    monkeypatch.setattr(github, "rename", services.rename)
    monkeypatch.setattr(packagist, "repository", lambda package: services.packagist.get(package))
    monkeypatch.setattr(packagist, "edit_repository", services.packagist.__setitem__)
    outcome.reset()
    return services


@pytest.fixture
def clone(tmp_path: Path) -> Path:
    git(tmp_path, "init", "--quiet", "--initial-branch", "main")
    git(tmp_path, "remote", "add", "origin", "git@github.com:me/old.git")
    return tmp_path


def origin(clone: Path) -> str:
    return git(clone, "config", "--get", "remote.origin.url")


def test_renaming_renames_the_repo_and_points_origin_at_the_new_name(services, clone):
    result = rename(clone, "new")
    assert services.names["me/old"] == "me/new"
    assert origin(clone) == "git@github.com:me/new.git"
    assert outcome.changes() == ["Renamed me/old to me/new", "Pointed origin at me/new"]
    assert isinstance(result, Done)
    assert result.details == ("https://github.com/me/new",)


def test_an_https_origin_keeps_its_form(services, clone):
    git(clone, "remote", "set-url", "origin", "https://github.com/me/old")
    rename(clone, "new")
    assert origin(clone) == "https://github.com/me/new"


def test_renaming_again_has_nothing_to_do(services, clone):
    rename(clone, "new")
    outcome.reset()
    result = rename(clone, "new")
    assert isinstance(result, NothingToDo)
    assert result.summary == "Already named me/new."


def test_a_repo_renamed_on_github_but_not_in_origin_only_has_origin_pointed_at_it(services, clone):
    services.rename("me/old", "new")
    rename(clone, "new")
    assert outcome.changes() == ["Pointed origin at me/new"]


def test_a_package_on_packagist_is_pointed_at_the_new_url(services, clone):
    (clone / "composer.json").write_text('{"name": "me/thing"}')
    services.packagist["me/thing"] = "https://github.com/me/old"
    rename(clone, "new")
    assert services.packagist["me/thing"] == "https://github.com/me/new"
    assert outcome.changes()[-1] == "Pointed me/thing on Packagist at https://github.com/me/new"


def test_a_package_not_on_packagist_is_left_off_it(services, clone):
    (clone / "composer.json").write_text('{"name": "me/thing"}')
    rename(clone, "new")
    assert services.packagist == {}


def test_a_new_name_with_an_owner_is_refused(services, clone):
    with pytest.raises(Precondition, match="without the owner"):
        rename(clone, "someone/new")
    assert services.names == {"me/old": "me/old"}


def test_a_repo_github_does_not_have_is_refused(services, clone):
    services.names = {}
    with pytest.raises(Precondition, match="gh can't see a repo me/old"):
        rename(clone, "new")


def test_a_clone_without_an_origin_is_refused(services, clone):
    git(clone, "remote", "remove", "origin")
    with pytest.raises(Precondition, match="No origin remote"):
        rename(clone, "new")
