"""packagist update from start to finish, with GitHub and Packagist replaced by fakes."""

import subprocess
from pathlib import Path

import pytest
from cli_kit import outcome
from cli_kit.outcome import Done, Failure, NothingToDo, Precondition

from repo_tools import clone
from repo_tools.packagist import api as packagist
from repo_tools.packagist.commands import update as update_module
from repo_tools.packagist.commands.update import update


class Packagist:
    def __init__(self) -> None:
        self.lacking: list[list[str] | None] = [[]]
        """What each look at the package finds it lacks; the last stays."""
        self.updates: list[str] = []

    def lacks(self, package: str, directory: Path) -> list[str] | None:
        return self.lacking.pop(0) if len(self.lacking) > 1 else self.lacking[0]


@pytest.fixture
def services(monkeypatch: pytest.MonkeyPatch) -> Packagist:
    services = Packagist()
    monkeypatch.setattr(clone, "origin_url", lambda directory: "git@github.com:me/thing.git")
    monkeypatch.setattr(packagist, "lacks", services.lacks)
    monkeypatch.setattr(packagist, "update", services.updates.append)
    monkeypatch.setattr(update_module, "WAIT_SECONDS", 0.2)
    monkeypatch.setattr(update_module, "POLL_SECONDS", 0)
    outcome.reset()
    return services


@pytest.fixture
def package(tmp_path: Path) -> Path:
    (tmp_path / "composer.json").write_text('{"name": "me/thing"}')
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)
    return tmp_path


def test_a_package_packagist_is_behind_on_is_updated_and_waited_for(services, package):
    services.lacking = [["v0.2.0"], ["v0.2.0"], []]
    result = update(package)
    assert services.updates == ["me/thing"]
    assert outcome.changes() == ["Asked Packagist to update me/thing"]
    assert isinstance(result, Done)
    assert (result.summary, result.details) == (
        "Updated.",
        ("https://packagist.org/packages/me/thing",),
    )


def test_a_package_packagist_is_up_to_date_on_has_nothing_to_do(services, package):
    result = update(package)
    assert isinstance(result, NothingToDo)
    assert result.summary == "Already up to date: https://packagist.org/packages/me/thing"
    assert services.updates == []


def test_an_update_that_does_not_land_in_time_fails_saying_what_is_still_lacking(services, package):
    services.lacking = [["main", "v0.2.0"]]
    with pytest.raises(Failure) as failure:
        update(package)
    assert failure.value.message == "Packagist still lacks main, v0.2.0."
    assert failure.value.details == (
        "It may still be queued, or Packagist may have rejected it, such as for an invalid",
        "composer.json at that version. The package's page says which:",
        "https://packagist.org/packages/me/thing",
    )


def test_a_package_not_on_packagist_is_refused(services, package):
    services.lacking = [None]
    with pytest.raises(Precondition, match="me/thing isn't on Packagist") as problem:
        update(package)
    assert problem.value.details == ("Run `packagist publish` first.",)
    assert services.updates == []


def test_a_package_without_an_origin_is_refused(services, package, monkeypatch):
    monkeypatch.setattr(clone, "origin_url", lambda directory: None)
    with pytest.raises(Precondition, match="No origin remote"):
        update(package)


def test_a_missing_directory_is_refused(services, tmp_path):
    with pytest.raises(Precondition, match="No such directory"):
        update(tmp_path / "missing")
