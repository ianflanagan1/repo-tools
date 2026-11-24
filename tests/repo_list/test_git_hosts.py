"""Behaviour of telling a remote's git host from its URL, and reading the git host a repository's
settings put its origin on."""

import pytest

from repo_list.config import Invalid
from repo_list.git_hosts import GitHost, LocalOnly, git_host_at, origin_git_host_in

WHERE = ".config/ianf-repo-tools.toml: remotes"


@pytest.mark.parametrize(
    ("url", "git_host"),
    [
        ("git@github.com:me/a.git", GitHost.GITHUB),
        ("https://github.com/me/a.git", GitHost.GITHUB),
        ("ssh://git@ssh.github.com:443/me/a.git", GitHost.GITHUB),
        ("git@bitbucket.org:me/a.git", GitHost.BITBUCKET),
        ("https://me@bitbucket.org/me/a.git", GitHost.BITBUCKET),
    ],
)
def test_a_git_host_is_told_by_its_domain_in_ssh_or_https_form(url, git_host):
    assert git_host_at(url) is git_host


@pytest.mark.parametrize(
    "url",
    [
        "git@gitlab.com:me/a.git",
        "git@notgithub.com:me/a.git",
        "git@github.example.com:me/a.git",
        "/srv/git/a.git",
        "",
    ],
)
def test_another_host_or_a_path_is_on_no_git_host(url):
    assert git_host_at(url) is None


def test_settings_with_no_remotes_put_origin_on_no_git_host():
    assert origin_git_host_in({"version": 1}, WHERE) is None


@pytest.mark.parametrize("git_host", list(GitHost))
def test_the_git_host_of_origin_is_read_from_its_table(git_host):
    table = {"remotes": {"origin": {"git-host": git_host.value}}}
    assert origin_git_host_in(table, WHERE) is git_host


def test_a_git_host_of_none_keeps_origin_local_only():
    table = {"remotes": {"origin": {"git-host": "none"}}}
    assert origin_git_host_in(table, WHERE) == LocalOnly()


@pytest.mark.parametrize(
    ("remotes", "message"),
    [
        ("github", f"{WHERE} must be a table of remotes, such as [remotes.origin]"),
        (
            {"mirror": {"git-host": "github"}},
            f"{WHERE} can only set origin for now, not mirror",
        ),
        ({"origin": "github"}, f"{WHERE}.origin must be a table"),
        ({"origin": {}}, f"{WHERE}.origin.git-host must be one of github, bitbucket, none"),
        (
            {"origin": {"git-host": "gitlab"}},
            f"{WHERE}.origin.git-host must be one of github, bitbucket, none",
        ),
        (
            {"origin": {"git-host": "github", "url": "x"}},
            f"{WHERE}.origin has an unknown setting url",
        ),
    ],
)
def test_remotes_that_cant_be_used_say_what_is_wrong(remotes, message):
    assert origin_git_host_in({"remotes": remotes}, WHERE) == Invalid(message)
