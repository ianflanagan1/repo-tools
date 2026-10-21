"""bitbucket delete, with the terminal, Bitbucket and the credential store replaced by fakes."""

import pytest
from cli_kit import credentials, terminal
from cli_kit.credentials import Credential, Token
from cli_kit.outcome import Precondition

from repo_tools.bitbucket import api
from repo_tools.bitbucket.commands.delete import DELETE_TOKEN, delete


class Fakes:
    def __init__(self) -> None:
        self.answer = "team/thing"
        self.prompts: list[str] = []
        self.tokens_read: list[Token] = []
        self.deleted_with: list[tuple[str, str]] = []


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch, bitbucket) -> Fakes:
    fakes = Fakes()
    bitbucket.repos["team/thing"] = {"full_name": "team/thing", "is_private": True}

    def ask(prompt: str) -> str:
        fakes.prompts.append(prompt)
        return fakes.answer

    def read(token: Token) -> Credential:
        fakes.tokens_read.append(token)
        return Credential("me@example.com", "delete-token")

    def delete_repo(client: api.Bitbucket, repo: str) -> None:
        fakes.deleted_with.append((repo, client._auth))

    monkeypatch.setattr(terminal, "ask", ask)
    monkeypatch.setattr(credentials.Token, "read", read)
    monkeypatch.setattr(api.Bitbucket, "delete", delete_repo)
    return fakes


def test_deletes_with_the_delete_token_once_the_full_name_is_typed(fakes: Fakes):
    assert delete("team/thing").summary == "Deleted."
    assert fakes.tokens_read == [DELETE_TOKEN]
    expected = api.Bitbucket(Credential("me@example.com", "delete-token"))._auth
    assert fakes.deleted_with == [("team/thing", expected)]


def test_the_delete_token_is_stored_so_macos_asks_for_your_password_on_each_read():
    assert DELETE_TOKEN.confirm_each_read


def test_asks_for_the_full_name_of_a_repo_given_by_bare_name(fakes: Fakes):
    delete("thing")
    assert "Type team/thing to confirm" in fakes.prompts[0]


def test_the_prompt_names_the_repo_url_and_visibility(fakes: Fakes):
    delete("team/thing")
    assert "Delete https://bitbucket.org/team/thing (private)?" in fakes.prompts[0]


def test_anything_but_the_full_name_deletes_nothing_and_reads_no_token(fakes: Fakes):
    fakes.answer = "thing"
    with pytest.raises(Precondition, match="Not confirmed"):
        delete("team/thing")
    assert fakes.tokens_read == []
    assert fakes.deleted_with == []


def test_a_repo_bitbucket_does_not_have_stops_it_before_asking(fakes: Fakes):
    with pytest.raises(Precondition, match="No Bitbucket repo team/missing"):
        delete("team/missing")
    assert fakes.prompts == []
