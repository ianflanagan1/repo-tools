"""bitbucket rename from start to finish, with Bitbucket and Packagist replaced by fakes."""

import subprocess
from pathlib import Path

import pytest
from cli_kit import outcome
from cli_kit.outcome import Done, NothingToDo, Precondition

from repo_tools.bitbucket.commands.rename import rename
from repo_tools.packagist import api as packagist


def git(directory: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(directory), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def stored(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """The repository URL of each package Packagist has."""
    stored: dict[str, str] = {}
    monkeypatch.setattr(packagist, "repository", stored.get)
    monkeypatch.setattr(packagist, "edit_repository", stored.__setitem__)
    return stored


@pytest.fixture
def clone(tmp_path: Path, bitbucket) -> Path:
    bitbucket.repos["team/old"] = {"full_name": "team/old", "is_private": False}
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "remote", "add", "origin", "git@bitbucket.org:team/old.git")
    return tmp_path


def test_renames_the_repo_and_points_origin_at_it(bitbucket, clone, stored):
    result = rename(clone, "new")
    assert bitbucket.renamed == [("team/old", "new")]
    assert git(clone, "remote", "get-url", "origin") == "git@bitbucket.org:team/new.git"
    assert isinstance(result, Done)
    assert result.details == ("https://bitbucket.org/team/new",)


def test_points_the_package_on_packagist_at_the_new_url(bitbucket, clone, stored):
    (clone / "composer.json").write_text('{"name": "me/thing"}')
    stored["me/thing"] = "https://bitbucket.org/team/old"
    rename(clone, "new")
    assert stored["me/thing"] == "https://bitbucket.org/team/new"


def test_leaves_a_package_packagist_has_from_elsewhere(bitbucket, clone, stored):
    (clone / "composer.json").write_text('{"name": "me/thing"}')
    stored["me/thing"] = "https://github.com/me/thing"
    rename(clone, "new")
    assert stored["me/thing"] == "https://github.com/me/thing"


def test_running_it_again_after_bitbucket_renamed_it_finishes_the_job(bitbucket, clone, stored):
    bitbucket.rename("team/old", "new")
    bitbucket.renamed.clear()
    bitbucket.redirects.clear()
    rename(clone, "new")
    assert bitbucket.renamed == []
    assert git(clone, "remote", "get-url", "origin") == "git@bitbucket.org:team/new.git"


def test_running_it_again_when_done_has_nothing_to_do(bitbucket, clone, stored):
    rename(clone, "new")
    outcome.reset()
    assert isinstance(rename(clone, "new"), NothingToDo)


def test_a_name_with_the_workspace_is_refused(bitbucket, clone, stored):
    with pytest.raises(Precondition, match="without the workspace"):
        rename(clone, "team/new")


def test_a_repo_bitbucket_does_not_have_stops_it(bitbucket, clone, stored):
    bitbucket.repos.clear()
    with pytest.raises(Precondition, match="No Bitbucket repo team/old or team/new"):
        rename(clone, "new")
