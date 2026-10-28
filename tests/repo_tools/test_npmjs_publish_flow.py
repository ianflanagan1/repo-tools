"""npmjs publish from start to finish, with GitHub and npm replaced by fakes."""

import subprocess
from pathlib import Path

import pytest
from cli_kit import outcome
from cli_kit.outcome import Done, NothingToDo, Precondition

from repo_tools import clone
from repo_tools.github import api as github
from repo_tools.npmjs import api as npm
from repo_tools.npmjs.commands.publish import publish


class Services:
    def __init__(self) -> None:
        self.visibility = "public"
        self.user: str | None = "me"
        self.two_factor = True
        self.versions: frozenset[str] | None = None
        self.published: list[tuple[str, str]] = []
        self.configs: list[dict] = []

    def publish(self, directory: Path, version: str) -> None:
        self.published.append((directory.name, version))
        self.versions = frozenset({version})

    def trust(self, directory: Path, package: str, repo: str) -> None:
        self.configs.append({"type": "github", "file": "publish.yml", "repository": repo})


@pytest.fixture
def services(monkeypatch: pytest.MonkeyPatch) -> Services:
    services = Services()
    monkeypatch.setattr(clone, "origin_url", lambda directory: "git@github.com:me/thing.git")
    monkeypatch.setattr(github, "visibility", lambda repo: services.visibility)
    monkeypatch.setattr(npm, "logged_in_as", lambda directory: services.user)
    monkeypatch.setattr(npm, "has_two_factor", lambda directory: services.two_factor)
    monkeypatch.setattr(npm, "versions", lambda package: services.versions)
    monkeypatch.setattr(npm, "publish", services.publish)
    monkeypatch.setattr(npm, "trusts", lambda directory, package: services.configs)
    monkeypatch.setattr(npm, "trust", services.trust)
    outcome.reset()
    return services


def git(directory: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(directory), *args], check=True, capture_output=True)


@pytest.fixture
def package(tmp_path: Path) -> Path:
    directory = tmp_path / "thing"
    (directory / ".github" / "workflows").mkdir(parents=True)
    (directory / ".github" / "workflows" / "publish.yml").write_text("on: push\n")
    (directory / "devbox.json").write_text("{}")
    (directory / "package.json").write_text(
        '{"name": "@me/thing", "version": "0.0.0",'
        ' "repository": {"url": "git+https://github.com/me/thing.git"}}'
    )
    git(directory.parent, "init", "-q", "-b", "main", "thing")
    git(directory, "add", "-A")
    git(directory, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "First")
    git(directory, "tag", "v0.1.0")
    return directory


def test_publishing_a_new_package_publishes_its_tagged_version_and_trusts_the_workflow(
    services, package
):
    result = publish(package)
    assert services.published == [("thing", "0.1.0")]
    assert services.configs == [{"type": "github", "file": "publish.yml", "repository": "me/thing"}]
    assert outcome.changes() == [
        "Published @me/thing@0.1.0",
        "Trusted me/thing's publish.yml to publish @me/thing",
    ]
    assert isinstance(result, Done)
    assert result.details == ("https://www.npmjs.com/package/@me/thing",)


def test_publishing_again_has_nothing_to_do(services, package):
    publish(package)
    outcome.reset()
    result = publish(package)
    assert isinstance(result, NothingToDo)
    assert result.summary == "Already published: https://www.npmjs.com/package/@me/thing"
    assert len(services.published) == 1


def test_a_package_already_on_npm_only_gets_the_workflow_trusted(services, package):
    services.versions = frozenset({"0.1.0"})
    publish(package)
    assert services.published == []
    assert outcome.changes() == ["Trusted me/thing's publish.yml to publish @me/thing"]


def test_a_package_already_on_npm_needs_no_version_tag(services, package):
    services.versions = frozenset({"0.1.0"})
    git(package, "tag", "-d", "v0.1.0")
    assert isinstance(publish(package), Done)


def test_the_highest_version_tag_at_head_is_published(services, package):
    git(package, "tag", "v0.2.0")
    git(package, "tag", "latest")
    publish(package)
    assert services.published == [("thing", "0.2.0")]


def test_a_new_package_without_a_version_tag_at_head_is_refused(services, package):
    git(package, "tag", "-d", "v0.1.0")
    with pytest.raises(Precondition, match="HEAD has no version tag") as problem:
        publish(package)
    assert problem.value.details == (
        f"Run `github release {package} minor` first; its tag is the version published.",
    )
    assert services.published == []


def test_a_new_package_with_uncommitted_changes_is_refused(services, package):
    (package / "README.md").write_text("draft\n")
    with pytest.raises(Precondition, match="Uncommitted changes"):
        publish(package)
    assert services.published == []


def test_another_trusted_publisher_is_refused_rather_than_replaced(services, package):
    services.versions = frozenset({"0.1.0"})
    services.configs = [{"id": "a1", "type": "github", "file": "release.yml", "repository": "x/y"}]
    with pytest.raises(Precondition, match="already trusts another publisher") as problem:
        publish(package)
    assert problem.value.details == (
        "To replace it: npm trust revoke @me/thing --id=a1",
        "Then run `npmjs publish` again.",
    )


def test_a_private_repo_is_refused_before_anything_changes(services, package):
    services.visibility = "private"
    with pytest.raises(Precondition, match="npm provenance needs a public repo"):
        publish(package)
    assert services.published == []


def test_a_repository_in_package_json_other_than_origin_is_refused(services, package):
    (package / "package.json").write_text(
        '{"name": "@me/thing", "repository": "https://github.com/me/other"}'
    )
    with pytest.raises(Precondition, match="package.json names me/other, but origin is me/thing"):
        publish(package)


def test_a_package_without_the_publish_workflow_is_refused(services, package):
    (package / ".github" / "workflows" / "publish.yml").unlink()
    with pytest.raises(Precondition, match="No .github/workflows/publish.yml"):
        publish(package)


def test_a_package_without_a_devbox_is_refused(services, package):
    (package / "devbox.json").unlink()
    with pytest.raises(Precondition, match="No devbox.json"):
        publish(package)


def test_publishing_when_not_logged_in_to_npm_is_refused(services, package):
    services.user = None
    with pytest.raises(Precondition, match="Not logged in to npm") as problem:
        publish(package)
    assert problem.value.details == (f"Run `devbox run -- npm login` in {package}.",)


def test_an_npm_account_without_two_factor_authentication_is_refused(services, package):
    services.two_factor = False
    with pytest.raises(Precondition, match="Two-factor authentication is off") as problem:
        publish(package)
    assert problem.value.details == (
        "npm needs it to publish and to trust a workflow.",
        "Turn it on for authorization and writes at https://www.npmjs.com/settings/me/tfa,",
        "then run `npmjs publish` again.",
    )
    assert services.published == []
