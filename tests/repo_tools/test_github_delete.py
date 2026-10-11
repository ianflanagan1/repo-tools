"""github delete, with the terminal, GitHub and the credential store replaced by fakes."""

import pytest
from cli_kit import credentials, terminal
from cli_kit.credentials import Credential
from cli_kit.errors import Precondition

from repo_tools.github import api
from repo_tools.github.commands.delete import DELETE_TOKEN_SERVICE, delete


class Fakes:
    def __init__(self) -> None:
        self.answer = "me/thing"
        self.prompts: list[str] = []
        self.services_read: list[str] = []
        self.deleted: list[tuple[str, str]] = []


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch) -> Fakes:
    fakes = Fakes()

    def ask(prompt: str) -> str:
        fakes.prompts.append(prompt)
        return fakes.answer

    def credential(service: str) -> Credential:
        fakes.services_read.append(service)
        return Credential("me", "delete-token")

    monkeypatch.setattr(api, "current_user", lambda: "me")
    monkeypatch.setattr(api, "exists", lambda repo: repo == "me/thing")
    monkeypatch.setattr(api, "visibility", lambda repo: "public")
    monkeypatch.setattr(api, "delete", lambda repo, token: fakes.deleted.append((repo, token)))
    monkeypatch.setattr(terminal, "ask", ask)
    monkeypatch.setattr(credentials, "credential", credential)
    return fakes


def test_deletes_with_the_delete_token_once_the_full_name_is_typed(fakes: Fakes):
    assert delete("me/thing").summary == "Deleted."
    assert fakes.services_read == [DELETE_TOKEN_SERVICE]
    assert fakes.deleted == [("me/thing", "delete-token")]


def test_asks_for_the_full_name_of_a_repo_given_by_bare_name(fakes: Fakes):
    delete("thing")
    assert "Type me/thing to confirm" in fakes.prompts[0]
    assert fakes.deleted == [("me/thing", "delete-token")]


def test_the_prompt_names_the_repo_url_and_visibility(fakes: Fakes):
    delete("me/thing")
    assert "Delete https://github.com/me/thing (public)?" in fakes.prompts[0]


def test_deletes_nothing_and_reads_no_token_when_another_name_is_typed(fakes: Fakes):
    fakes.answer = "thing"
    with pytest.raises(Precondition, match="Not confirmed"):
        delete("me/thing")
    assert fakes.services_read == []
    assert fakes.deleted == []


def test_deletes_nothing_without_a_terminal(fakes: Fakes, monkeypatch: pytest.MonkeyPatch):
    def no_terminal(prompt: str) -> str:
        raise Precondition("No terminal to confirm at.")

    monkeypatch.setattr(terminal, "ask", no_terminal)
    with pytest.raises(Precondition, match="No terminal"):
        delete("me/thing")
    assert fakes.services_read == []
    assert fakes.deleted == []


def test_asks_nothing_for_a_repo_gh_cannot_see(fakes: Fakes):
    with pytest.raises(Precondition, match="can't see a repo me/missing"):
        delete("me/missing")
    assert fakes.prompts == []
