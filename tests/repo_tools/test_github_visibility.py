"""github visibility, with GitHub replaced by fakes."""

import pytest
from cli_kit.outcome import Done, NothingToDo, Precondition

from repo_tools.github import api
from repo_tools.github.commands.visibility import set_visibility


class Fakes:
    def __init__(self) -> None:
        self.visibility = {"me/thing": "public"}
        self.set_calls: list[tuple[str, str]] = []


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch) -> Fakes:
    fakes = Fakes()

    def set_repo_visibility(repo: str, visibility: str) -> None:
        fakes.set_calls.append((repo, visibility))
        fakes.visibility[repo] = visibility

    monkeypatch.setattr(api, "current_user", lambda: "me")
    monkeypatch.setattr(api, "exists", lambda repo: repo in fakes.visibility)
    monkeypatch.setattr(api, "visibility", lambda repo: fakes.visibility[repo])
    monkeypatch.setattr(api, "set_visibility", set_repo_visibility)
    return fakes


def test_makes_a_public_repo_private_and_gives_its_url(fakes: Fakes):
    result = set_visibility("me/thing", "private")
    assert fakes.set_calls == [("me/thing", "private")]
    assert isinstance(result, Done)
    assert (result.summary, result.details) == (
        "Made private.",
        ("https://github.com/me/thing",),
    )


def test_makes_a_private_repo_public(fakes: Fakes):
    fakes.visibility["me/thing"] = "private"
    set_visibility("me/thing", "public")
    assert fakes.set_calls == [("me/thing", "public")]


def test_changes_a_repo_given_by_bare_name_under_the_current_user(fakes: Fakes):
    set_visibility("thing", "private")
    assert fakes.set_calls == [("me/thing", "private")]


def test_has_nothing_to_do_for_a_repo_that_already_has_that_visibility(fakes: Fakes):
    result = set_visibility("me/thing", "public")
    assert fakes.set_calls == []
    assert isinstance(result, NothingToDo)
    assert result.summary == "me/thing is already public."


def test_fails_for_a_repo_gh_cannot_see(fakes: Fakes):
    with pytest.raises(Precondition, match="can't see a repo me/missing"):
        set_visibility("me/missing", "private")
    assert fakes.set_calls == []
