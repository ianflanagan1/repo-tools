"""npmjs wait from start to finish, with npm replaced by a fake."""

import subprocess
from pathlib import Path

import pytest
from cli_kit import outcome
from cli_kit.outcome import Done, Failure, NothingToDo, Precondition

from repo_tools import clone
from repo_tools.npmjs import api as npm
from repo_tools.npmjs.commands import wait as wait_module
from repo_tools.npmjs.commands.wait import wait


class Npm:
    def __init__(self) -> None:
        self.lacking: list[list[str] | None] = [[]]
        """What each look at the package finds it lacks; the last stays."""

    def lacks(self, package: str, directory: Path) -> list[str] | None:
        return self.lacking.pop(0) if len(self.lacking) > 1 else self.lacking[0]


@pytest.fixture
def services(monkeypatch: pytest.MonkeyPatch) -> Npm:
    services = Npm()
    monkeypatch.setattr(clone, "origin_url", lambda directory: "git@github.com:me/thing.git")
    monkeypatch.setattr(npm, "lacks", services.lacks)
    monkeypatch.setattr(wait_module, "WAIT_SECONDS", 0.2)
    monkeypatch.setattr(wait_module, "POLL_SECONDS", 0)
    outcome.reset()
    return services


@pytest.fixture
def package(tmp_path: Path) -> Path:
    (tmp_path / "package.json").write_text('{"name": "@me/thing"}')
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)
    return tmp_path


def test_a_version_npm_lacks_is_waited_for(services, package):
    services.lacking = [["v0.2.0"], ["v0.2.0"], []]
    result = wait(package)
    assert isinstance(result, Done)
    assert (result.summary, result.details) == (
        "Published.",
        ("https://www.npmjs.com/package/@me/thing",),
    )


def test_a_package_npm_is_up_to_date_on_has_nothing_to_do(services, package):
    result = wait(package)
    assert isinstance(result, NothingToDo)
    assert result.summary == "Already published: https://www.npmjs.com/package/@me/thing"


def test_a_version_that_does_not_land_in_time_fails_saying_where_to_look(services, package):
    services.lacking = [["v0.2.0", "v0.3.0"]]
    with pytest.raises(Failure) as failure:
        wait(package)
    assert failure.value.message == "npm still lacks v0.2.0, v0.3.0."
    assert failure.value.details == (
        "The publish workflow may still be running, or it failed. Its runs:",
        "https://github.com/me/thing/actions/workflows/publish.yml",
    )


def test_a_package_not_on_npm_is_refused(services, package):
    services.lacking = [None]
    with pytest.raises(Precondition, match="@me/thing isn't on npm") as problem:
        wait(package)
    assert problem.value.details == ("Run `npmjs publish` first.",)


def test_a_package_without_an_origin_is_refused(services, package, monkeypatch):
    monkeypatch.setattr(clone, "origin_url", lambda directory: None)
    with pytest.raises(Precondition, match="No origin remote"):
        wait(package)


def test_a_missing_directory_is_refused(services, tmp_path):
    with pytest.raises(Precondition, match="No such directory"):
        wait(tmp_path / "missing")
