"""github archive, with GitHub replaced by fakes."""

import pytest
from cli_kit.outcome import Done, NothingToDo, Precondition

from repo_tools.github import api
from repo_tools.github.commands.archive import archive


class Fakes:
    def __init__(self) -> None:
        self.archived: set[str] = set()
        self.archive_calls: list[str] = []


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch) -> Fakes:
    fakes = Fakes()

    def archive_repo(repo: str) -> None:
        fakes.archive_calls.append(repo)
        fakes.archived.add(repo)

    monkeypatch.setattr(api, "current_user", lambda: "me")
    monkeypatch.setattr(api, "exists", lambda repo: repo == "me/thing")
    monkeypatch.setattr(api, "is_archived", lambda repo: repo in fakes.archived)
    monkeypatch.setattr(api, "archive", archive_repo)
    return fakes


def test_archives_the_repo_and_gives_its_url(fakes: Fakes):
    result = archive("me/thing")
    assert fakes.archive_calls == ["me/thing"]
    assert isinstance(result, Done)
    assert (result.summary, result.details) == ("Archived.", ("https://github.com/me/thing",))


def test_archives_a_repo_given_by_bare_name_under_the_current_user(fakes: Fakes):
    archive("thing")
    assert fakes.archive_calls == ["me/thing"]


def test_has_nothing_to_do_for_a_repo_that_is_already_archived(fakes: Fakes):
    fakes.archived.add("me/thing")
    result = archive("me/thing")
    assert fakes.archive_calls == []
    assert isinstance(result, NothingToDo)
    assert result.summary == "me/thing is already archived."


def test_fails_for_a_repo_gh_cannot_see(fakes: Fakes):
    with pytest.raises(Precondition, match="can't see a repo me/missing"):
        archive("me/missing")
    assert fakes.archive_calls == []
