"""What Packagist offers of a package, read from its Composer metadata, and what it lacks of the
package's origin, which is a local bare repository behind a github.com URL."""

import subprocess
from pathlib import Path

import pytest

from repo_tools.packagist import api
from repo_tools.packagist.api import Offered


def git(directory: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(directory), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def metadata(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[dict] | None]:
    """The p2 files Packagist serves, by URL; a URL not here is a 404."""
    files: dict[str, list[dict] | None] = {}
    monkeypatch.setattr(api, "_p2", lambda url: files.get(url))
    return files


TAGGED = "https://repo.packagist.org/p2/me/thing.json"
DEV = "https://repo.packagist.org/p2/me/thing~dev.json"


def test_a_package_packagist_has_no_metadata_for_is_not_offered(metadata):
    assert api.offered("me/thing") is None


def test_the_offer_is_each_tagged_version_and_the_commit_of_each_dev_branch(metadata):
    metadata[TAGGED] = [
        {"version": "v0.2.0", "source": {"reference": "bbb"}},
        {"version": "v0.1.0", "source": {"reference": "aaa"}},
    ]
    metadata[DEV] = [{"version": "dev-main", "source": {"reference": "ccc"}}]
    assert api.offered("me/thing") == Offered(frozenset({"v0.2.0", "v0.1.0"}), frozenset({"ccc"}))


def test_minified_metadata_carries_each_field_on_from_the_version_before(metadata):
    metadata[TAGGED] = [
        {"version": "v0.2.0", "source": {"reference": "aaa"}},
        {"version": "v0.1.0"},
    ]
    metadata[DEV] = [
        {"version": "dev-main", "source": {"reference": "ccc"}},
        {"version": "dev-other"},
        {"version": "dev-gone", "source": "__unset"},
    ]
    assert api.offered("me/thing") == Offered(frozenset({"v0.2.0", "v0.1.0"}), frozenset({"ccc"}))


def test_a_package_with_only_dev_branches_is_offered(metadata):
    metadata[DEV] = [{"version": "dev-main", "source": {"reference": "ccc"}}]
    assert api.offered("me/thing") == Offered(frozenset(), frozenset({"ccc"}))


@pytest.fixture
def package(tmp_path: Path) -> Path:
    """A package with one commit on main, pushed to an origin that is a github.com URL."""
    package = tmp_path / "thing"
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(remote))
    package.mkdir()
    git(package, "init", "-q", "-b", "main")
    git(package, "config", "user.name", "t")
    git(package, "config", "user.email", "t@t")
    git(package, "config", f"url.{remote}.insteadOf", "git@github.com:me/thing.git")
    git(package, "remote", "add", "origin", "git@github.com:me/thing.git")
    git(package, "commit", "-q", "--allow-empty", "-m", "init")
    git(package, "push", "-q", "origin", "main")
    return package


def offers(monkeypatch: pytest.MonkeyPatch, versions: set[str], commits: set[str]) -> None:
    offered = Offered(frozenset(versions), frozenset(commits))
    monkeypatch.setattr(api, "offered", lambda package: offered)


def test_a_package_offering_everything_on_origin_lacks_nothing(package, monkeypatch):
    git(package, "tag", "-a", "-m", "v0.1.0", "v0.1.0")
    git(package, "push", "-q", "origin", "v0.1.0")
    offers(monkeypatch, {"v0.1.0"}, {git(package, "rev-parse", "main")})
    assert api.lacks("me/thing", package) == []


def test_it_lacks_each_version_tag_on_origin_it_does_not_offer(package, monkeypatch):
    git(package, "tag", "v0.1.0")
    git(package, "tag", "v0.2.0-beta1")
    git(package, "push", "-q", "origin", "--tags")
    offers(monkeypatch, {"v0.1.0"}, {git(package, "rev-parse", "main")})
    assert api.lacks("me/thing", package) == ["v0.2.0-beta1"]


def test_it_lacks_each_branch_on_origin_whose_commit_it_does_not_offer(package, monkeypatch):
    offers(monkeypatch, set(), {git(package, "rev-parse", "main")})
    git(package, "commit", "-q", "--allow-empty", "-m", "more")
    git(package, "push", "-q", "origin", "main", "main:feature")
    assert api.lacks("me/thing", package) == ["feature", "main"]


def test_tags_that_are_not_versions_are_not_expected(package, monkeypatch):
    git(package, "tag", "latest")
    git(package, "push", "-q", "origin", "--tags")
    offers(monkeypatch, set(), {git(package, "rev-parse", "main")})
    assert api.lacks("me/thing", package) == []


def test_what_is_only_local_is_not_expected(package, monkeypatch):
    offers(monkeypatch, set(), {git(package, "rev-parse", "main")})
    git(package, "tag", "v0.1.0")
    git(package, "commit", "-q", "--allow-empty", "-m", "unpushed")
    assert api.lacks("me/thing", package) == []


def test_what_it_lacks_of_a_package_it_does_not_have_is_none(package, monkeypatch):
    monkeypatch.setattr(api, "offered", lambda package: None)
    assert api.lacks("me/thing", package) is None
