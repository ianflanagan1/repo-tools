import pytest
from cli_kit.outcome import Precondition

from repo_tools.github import api


@pytest.mark.parametrize(
    "url",
    [
        "git@github.com:someone/phpstan-foo.git",
        "git@github.com:someone/phpstan-foo",
        "https://github.com/someone/phpstan-foo.git",
        "https://github.com/someone/phpstan-foo",
        "ssh://git@github.com/someone/phpstan-foo.git",
    ],
)
def test_reads_the_repo_from_an_ssh_or_https_url(url: str):
    assert api.repo_from_url(url) == "someone/phpstan-foo"


def test_rejects_a_url_that_is_not_on_github():
    with pytest.raises(Precondition, match="not a GitHub repo"):
        api.repo_from_url("git@gitlab.com:someone/phpstan-foo.git")


def test_keeps_a_full_name_as_it_is():
    assert api.full_name("someone/thing") == "someone/thing"


def test_gives_a_bare_name_the_current_users_login(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(api, "current_user", lambda: "me")
    assert api.full_name("thing") == "me/thing"


def test_reads_a_repos_details_from_ghs_json():
    text = (
        '{"description": "A skill.", "visibility": "PRIVATE",'
        ' "repositoryTopics": [{"name": "claude-code"}, {"name": "claude-skills"}]}'
    )
    assert api.parse_details(text) == api.Details(
        "A skill.", "private", ("claude-code", "claude-skills")
    )


def test_reads_a_repo_with_no_topics_or_description_from_ghs_json():
    text = '{"description": "", "visibility": "PUBLIC", "repositoryTopics": null}'
    assert api.parse_details(text) == api.Details("", "public", ())
