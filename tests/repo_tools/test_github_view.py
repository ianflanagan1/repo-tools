"""github view, with GitHub replaced by fakes."""

import json

import pytest
from cli_kit.outcome import NothingToDo, Precondition

from repo_tools.github import api
from repo_tools.github.commands.view import view


@pytest.fixture(autouse=True)
def fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "current_user", lambda: "me")
    monkeypatch.setattr(api, "exists", lambda repo: repo == "me/thing")
    found = api.Details("A Claude Code skill.", "public", ("claude-code", "claude-skills"))
    monkeypatch.setattr(api, "details", lambda repo: found)


def test_prints_the_repos_details_as_one_json_object(capsys: pytest.CaptureFixture[str]):
    view("me/thing")
    assert json.loads(capsys.readouterr().out) == {
        "repo": "me/thing",
        "visibility": "public",
        "description": "A Claude Code skill.",
        "topics": ["claude-code", "claude-skills"],
    }


def test_ends_with_a_summary_and_changes_nothing():
    result = view("thing")
    assert isinstance(result, NothingToDo)
    assert result.summary == "me/thing is public, with 2 topics."


def test_fails_for_a_repo_gh_cannot_see():
    with pytest.raises(Precondition, match="can't see a repo me/missing"):
        view("me/missing")
