"""packagist publish from start to finish, with GitHub and Packagist replaced by fakes."""

import subprocess
from pathlib import Path

import pytest
from cli_kit import outcome
from cli_kit.errors import Precondition
from cli_kit.outcome import Done, NothingToDo

from repo_tools.github import api as github
from repo_tools.packagist import api as packagist
from repo_tools.packagist.commands.publish import publish


class Services:
    def __init__(self) -> None:
        self.visibility = "public"
        self.packages: set[str] = set()
        self.hooks: list[str] = []


@pytest.fixture
def services(monkeypatch: pytest.MonkeyPatch) -> Services:
    services = Services()

    def add_hook(repo: str, url: str, secret: str) -> None:
        services.hooks.append(url)

    monkeypatch.setattr(github, "origin_url", lambda directory: "git@github.com:me/thing.git")
    monkeypatch.setattr(github, "visibility", lambda repo: services.visibility)
    monkeypatch.setattr(github, "hook_urls", lambda repo: services.hooks)
    monkeypatch.setattr(github, "add_hook", add_hook)
    monkeypatch.setattr(packagist, "package_exists", lambda package: package in services.packages)
    monkeypatch.setattr(packagist, "submit", lambda url: services.packages.add("me/thing"))
    monkeypatch.setattr(
        packagist, "github_hook", lambda: ("https://packagist.org/api/github?username=me", "s")
    )
    outcome.reset()
    return services


@pytest.fixture
def package(tmp_path: Path) -> Path:
    (tmp_path / "composer.json").write_text('{"name": "me/thing"}')
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)
    return tmp_path


def test_publishing_submits_the_package_and_adds_the_webhook(services, package):
    result = publish(package)
    assert outcome.changes() == ["Submitted me/thing", "Added the Packagist webhook"]
    assert isinstance(result, Done)
    assert result.details == ("https://packagist.org/packages/me/thing",)


def test_publishing_again_has_nothing_to_do(services, package):
    publish(package)
    outcome.reset()
    result = publish(package)
    assert isinstance(result, NothingToDo)
    assert result.summary == "Already published: https://packagist.org/packages/me/thing"


def test_a_private_repo_is_refused_before_anything_changes(services, package):
    services.visibility = "private"
    with pytest.raises(Precondition, match="Packagist needs a public repo"):
        publish(package)
    assert services.packages == set()
