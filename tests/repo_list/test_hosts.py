"""Behaviour of telling a remote's host from its URL."""

import pytest

from repo_list.hosts import GitHub, NotOpened, Unknown, host_icon
from repo_list.report import width
from repo_tools.github import api as github


@pytest.mark.parametrize(
    ("url", "icon"),
    [
        ("git@github.com:me/a.git", "🐙"),
        ("https://github.com/me/a.git", "🐙"),
        ("ssh://git@gitlab.com/me/a.git", "🦊"),
        ("git@bitbucket.org:me/a.git", "🧺"),
        ("https://me@bitbucket.org/me/a.git", "🧺"),
        ("https://codeberg.org/me/a.git", "🗻"),
        ("https://me@dev.azure.com/me/project/_git/a", "🔷"),
        ("https://me.visualstudio.com/project/_git/a", "🔷"),
    ],
)
def test_each_known_host_is_told_by_its_domain_in_ssh_or_https_form(url, icon):
    assert host_icon(url) == icon


@pytest.mark.parametrize(
    "url", ["git@git.example.com:me/a.git", "/srv/git/a.git", "file:///srv/git/a.git", ""]
)
def test_any_other_host_or_a_path_is_another_host(url):
    assert host_icon(url) == "❔"


def test_a_domain_that_only_contains_a_known_one_is_another_host():
    assert host_icon("git@notgithub.com:me/a.git") == "❔"


def test_every_host_icon_is_two_columns_wide():
    urls = ["github.com", "gitlab.com", "bitbucket.org", "codeberg.org", "dev.azure.com", "x"]
    assert [width(host_icon(f"https://{u}/a")) for u in urls] == [2] * len(urls)


def test_github_answers_unknown_rather_than_failing_when_gh_is_missing(monkeypatch):
    def missing(*args):
        raise FileNotFoundError(2, "No such file or directory", "gh")

    monkeypatch.setattr(github, "visibility", missing)
    monkeypatch.setattr(github, "open_pull_requests", missing)
    monkeypatch.setattr(github, "create_draft_pull_request", missing)
    host = GitHub("me/a")
    assert host.visibility() == Unknown("gh isn't installed")
    assert host.open_for("feature") == Unknown("gh isn't installed")
    assert host.open_draft("feature", "main", "t", "b") == NotOpened(("gh isn't installed",))
