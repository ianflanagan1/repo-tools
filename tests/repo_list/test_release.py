"""Behaviour of which command releases a repository, by the host its origin is on."""

from repo_list.plugins import github, release


def test_a_repository_on_github_is_released_with_github_release():
    assert release.command_for("git@github.com:me/a.git") == github.GITHUB


def test_a_repository_on_bitbucket_is_released_with_bitbucket_release():
    assert release.command_for("https://bitbucket.org/me/a.git") == release.BITBUCKET


def test_a_repository_on_another_host_has_no_release_command():
    assert release.command_for("https://gitlab.com/me/a.git") is None
