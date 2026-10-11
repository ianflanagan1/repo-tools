import subprocess

import pytest
from cli_kit.errors import Precondition

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


def test_reads_origin_as_configured_ignoring_url_rewrites(tmp_path):
    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)

    git("init", "-q")
    git("remote", "add", "origin", "git@github.com:me/thing.git")
    git("config", "url./somewhere/else.git.insteadOf", "git@github.com:me/thing.git")
    assert api.origin_url(tmp_path) == "git@github.com:me/thing.git"


def test_has_no_origin_for_a_repo_without_one(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    assert api.origin_url(tmp_path) is None
