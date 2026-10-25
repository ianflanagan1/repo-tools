"""github edit, with GitHub replaced by fakes."""

import pytest
from cli_kit.outcome import Done, NothingToDo, Precondition

from repo_tools.github import api
from repo_tools.github.commands.edit import edit


class Fakes:
    def __init__(self) -> None:
        self.details = api.Details("Old.", "public", ("claude-code",))
        self.edit_calls: list[tuple[str, str | None, tuple[str, ...]]] = []


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch) -> Fakes:
    fakes = Fakes()

    def edit_repo(repo: str, description: str | None, add_topics: tuple[str, ...]) -> None:
        fakes.edit_calls.append((repo, description, add_topics))

    monkeypatch.setattr(api, "current_user", lambda: "me")
    monkeypatch.setattr(api, "exists", lambda repo: repo == "me/thing")
    monkeypatch.setattr(api, "details", lambda repo: fakes.details)
    monkeypatch.setattr(api, "edit", edit_repo)
    return fakes


def test_sets_the_description_and_gives_the_repos_url(fakes: Fakes):
    result = edit("thing", "New.", [])
    assert fakes.edit_calls == [("me/thing", "New.", ())]
    assert isinstance(result, Done)
    assert (result.summary, result.details) == ("Edited.", ("https://github.com/me/thing",))


def test_adds_only_the_topics_the_repo_does_not_have(fakes: Fakes):
    edit("me/thing", None, ["claude-code", "claude-skills"])
    assert fakes.edit_calls == [("me/thing", None, ("claude-skills",))]


def test_leaves_out_a_description_the_repo_already_has(fakes: Fakes):
    edit("me/thing", "Old.", ["claude-skills"])
    assert fakes.edit_calls == [("me/thing", None, ("claude-skills",))]


def test_has_nothing_to_do_when_the_repo_already_matches(fakes: Fakes):
    result = edit("me/thing", "Old.", ["claude-code"])
    assert fakes.edit_calls == []
    assert isinstance(result, NothingToDo)
    assert result.summary == "me/thing already has that description and those topics."


def test_refuses_a_call_that_changes_nothing(fakes: Fakes):
    with pytest.raises(Precondition, match="--description or --add-topic"):
        edit("me/thing", None, [])


def test_refuses_a_description_longer_than_github_allows(fakes: Fakes):
    with pytest.raises(Precondition, match="350"):
        edit("me/thing", "x" * 351, [])
    assert fakes.edit_calls == []


def test_fails_for_a_repo_gh_cannot_see(fakes: Fakes):
    with pytest.raises(Precondition, match="can't see a repo me/missing"):
        edit("me/missing", "New.", [])
