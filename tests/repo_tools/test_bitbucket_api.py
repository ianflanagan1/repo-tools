"""Bitbucket's API client, with Bitbucket replaced by a fake urlopen."""

import base64
import io
import json
import urllib.error

import pytest
from cli_kit.credentials import Credential
from cli_kit.outcome import Failure, Precondition

from repo_tools.bitbucket import api


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class Server:
    """Answers each request with the next of answers: a dict as JSON, a str as it is, or an
    int as that HTTP error, and records each request."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.answers: list = []
        self.requests: list = []
        monkeypatch.setattr(api.urllib.request, "urlopen", self.urlopen)

    def urlopen(self, request):
        self.requests.append(request)
        answer = self.answers.pop(0)
        if isinstance(answer, int):
            body = json.dumps({"type": "error", "error": {"message": "Nope"}}).encode()
            raise urllib.error.HTTPError(request.full_url, answer, "", {}, io.BytesIO(body))
        return Response(answer.encode() if isinstance(answer, str) else json.dumps(answer).encode())


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> Server:
    return Server(monkeypatch)


@pytest.fixture
def client() -> api.Bitbucket:
    return api.Bitbucket(Credential("me@example.com", "secret"))


@pytest.mark.parametrize(
    "url",
    [
        "git@bitbucket.org:team/app.git",
        "git@bitbucket.org:team/app",
        "https://me@bitbucket.org/team/app.git",
        "https://bitbucket.org/team/app",
        "ssh://git@bitbucket.org/team/app.git",
    ],
)
def test_reads_the_repo_from_an_ssh_or_https_url(url: str):
    assert api.repo_from_url(url) == "team/app"


def test_rejects_a_url_that_is_not_on_bitbucket():
    with pytest.raises(Precondition, match="not a Bitbucket repo"):
        api.repo_from_url("git@github.com:team/app.git")


@pytest.mark.parametrize(
    ("url", "renamed"),
    [
        ("git@bitbucket.org:team/old.git", "git@bitbucket.org:team/new.git"),
        ("https://me@bitbucket.org/team/old", "https://me@bitbucket.org/team/new"),
    ],
)
def test_renames_a_url_keeping_its_form(url: str, renamed: str):
    assert api.renamed_url(url, "team/new") == renamed


def test_signs_in_by_basic_auth_with_the_email_and_token(server, client):
    server.answers = [{"full_name": "team/app"}]
    client.repository("team/app")
    expected = base64.b64encode(b"me@example.com:secret").decode()
    assert server.requests[0].get_header("Authorization") == f"Basic {expected}"
    assert server.requests[0].full_url == "https://api.bitbucket.org/2.0/repositories/team/app"


def test_a_repo_it_cannot_see_is_none(server, client):
    server.answers = [404]
    assert client.repository("team/missing") is None


def test_reads_every_page_by_following_next(server, client):
    server.answers = [
        {"values": [{"hash": "a"}], "next": "https://api.bitbucket.org/2.0/page2"},
        {"values": [{"hash": "b"}]},
    ]
    assert [c["hash"] for c in client.commits("team/app", "main", "v1")] == ["a", "b"]
    assert server.requests[1].full_url == "https://api.bitbucket.org/2.0/page2"


def test_reads_pages_only_as_far_as_asked(server, client):
    server.answers = [{"values": [{"hash": "a"}], "next": "https://api.bitbucket.org/2.0/page2"}]
    next(iter(client.commits("team/app", "main", "v1")))
    assert len(server.requests) == 1


def test_asks_for_merged_pull_requests_updated_since_into_a_base(server, client):
    server.answers = [{"values": []}]
    list(client.merged_pull_requests("team/app", "2026-09-01T00:00:00+00:00", "main"))
    url = server.requests[0].full_url
    assert "updated_on+%3E%3D+2026-09-01T00%3A00%3A00%2B00%3A00" in url
    assert "destination.branch.name+%3D+%22main%22" in url


def test_a_refused_token_says_how_to_store_another(server, client):
    server.answers = [401]
    with pytest.raises(Precondition, match="refused the API token"):
        client.repository("team/app")


def test_a_forbidden_request_names_the_scopes_the_token_needs(server, client):
    server.answers = [403]
    with pytest.raises(Failure) as failure:
        client.environments("team/app")
    assert "Nope" in failure.value.details
    assert any("read:pipeline:bitbucket" in line for line in failure.value.details)


def test_another_error_gives_bitbuckets_message(server, client):
    server.answers = [400]
    with pytest.raises(Failure) as failure:
        client.create("team/app", True, "", None)
    assert failure.value.message == "Bitbucket answered 400."
    assert failure.value.details == ("Nope",)


def test_creates_a_repo_in_a_project_when_given(server, client):
    server.answers = [{}]
    client.create("team/app", True, "A thing", "PROJ")
    sent = json.loads(server.requests[0].data)
    assert sent == {
        "scm": "git",
        "is_private": True,
        "description": "A thing",
        "project": {"key": "PROJ"},
    }


def test_reads_the_log_of_the_first_failed_step(server, client):
    server.answers = [
        {
            "values": [
                {"uuid": "{1}", "state": {"result": {"name": "SUCCESSFUL"}}},
                {"uuid": "{2}", "state": {"result": {"name": "FAILED"}}},
            ]
        },
        "line 1\nline 2\n",
    ]
    assert client.failed_step_log("team/app", "{p}") == "line 1\nline 2\n"
    assert server.requests[1].full_url.endswith("/pipelines/{p}/steps/{2}/log")


def test_pipelines_are_off_for_a_repo_that_has_never_configured_them(server, client):
    server.answers = [404]
    assert client.pipelines_enabled("team/app") is False


def test_asks_for_a_step_log_as_text_not_json(server, client):
    server.answers = [{"values": [{"uuid": "{2}", "state": {"result": {"name": "FAILED"}}}]}, "log"]
    client.failed_step_log("team/app", "{p}")
    assert server.requests[1].get_header("Accept") == "text/plain, */*"


def test_asks_for_pages_no_longer_than_the_pull_requests_endpoint_allows(server, client):
    server.answers = [{"values": []}]
    list(client.merged_pull_requests("team/app", "2026-09-01T00:00:00+00:00", None))
    assert "pagelen=50" in server.requests[0].full_url


def test_a_forbidden_request_is_its_own_failure(server, client):
    server.answers = [403]
    with pytest.raises(api.Forbidden):
        client.pipelines_enabled("team/app")


def test_lists_pipeline_runs_newest_first(server, client):
    server.answers = [{"values": [{"uuid": "{2}"}, {"uuid": "{1}"}]}]
    assert [p["uuid"] for p in client.pipelines("team/app")] == ["{2}", "{1}"]
    assert "sort=-created_on" in server.requests[0].full_url


def test_reads_a_file_at_a_revision(server, client):
    server.answers = ["pipelines: {}\n"]
    assert client.file("team/app", "main", "bitbucket-pipelines.yml") == "pipelines: {}\n"
    assert server.requests[0].full_url.endswith(
        "/repositories/team/app/src/main/bitbucket-pipelines.yml"
    )


def test_a_file_the_revision_does_not_have_is_none(server, client):
    server.answers = [404]
    assert client.file("team/app", "main", "missing.yml") is None
