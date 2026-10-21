"""github release from start to finish, with GitHub's releases replaced by fakes and the GitHub
remote by a local bare repository, through git's url.<base>.insteadOf."""

import subprocess
from pathlib import Path

import pytest
from cli_kit import outcome
from cli_kit.outcome import Done, NothingToDo, Precondition

from repo_tools.github import api
from repo_tools.github.commands.release import release


def git(directory: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(directory), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def releases(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The GitHub releases created, as repo@tag."""
    created: list[str] = []
    monkeypatch.setattr(api, "release_exists", lambda repo, tag: f"{repo}@{tag}" in created)
    monkeypatch.setattr(api, "create_release", lambda repo, tag: created.append(f"{repo}@{tag}"))
    outcome.reset()
    return created


@pytest.fixture
def remote(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(remote))
    return remote


def clone_of(remote: Path, directory: Path) -> Path:
    """A clone whose origin is me/thing on GitHub, leading to remote."""
    directory.mkdir()
    git(directory, "init", "-q", "-b", "main")
    git(directory, "config", "user.name", "t")
    git(directory, "config", "user.email", "t@t")
    git(directory, "config", f"url.{remote}.insteadOf", "git@github.com:me/thing.git")
    git(directory, "remote", "add", "origin", "git@github.com:me/thing.git")
    return directory


@pytest.fixture
def project(tmp_path: Path, remote: Path) -> Path:
    """A clone with one commit, pushed."""
    project = clone_of(remote, tmp_path / "thing")
    commit_and_push(project)
    return project


def commit_and_push(project: Path) -> None:
    git(project, "commit", "-q", "--allow-empty", "-m", "change")
    git(project, "push", "-q", "-u", "origin", "main")


def tags_on(remote: Path) -> list[str]:
    return git(remote, "tag").splitlines()


# --- The version


@pytest.mark.parametrize(
    ("level", "version"), [("patch", "v0.0.1"), ("minor", "v0.1.0"), ("major", "v1.0.0")]
)
def test_the_first_release_bumps_0_0_0(releases, project, remote, level, version):
    release(project, level)
    assert tags_on(remote) == [version]


@pytest.mark.parametrize(
    ("level", "version"), [("patch", "v0.2.4"), ("minor", "v0.3.0"), ("major", "v1.0.0")]
)
def test_a_release_bumps_the_highest_version_tag(releases, project, remote, level, version):
    git(project, "tag", "v0.2.3")
    commit_and_push(project)
    git(project, "tag", "v0.1.9")
    commit_and_push(project)
    release(project, level)
    assert version in tags_on(remote)


def test_the_new_tag_keeps_the_highest_tags_style_without_a_v(releases, project, remote):
    git(project, "tag", "1.2.3")
    commit_and_push(project)
    release(project, "patch")
    assert "1.2.4" in tags_on(remote)


def test_tags_that_are_not_release_versions_are_ignored(releases, project, remote):
    git(project, "tag", "v0.1.0")
    git(project, "tag", "v9.0.0-beta1")
    git(project, "tag", "latest")
    commit_and_push(project)
    release(project, "patch")
    assert "v0.1.1" in tags_on(remote)


def test_a_tag_pushed_from_another_clone_is_counted(releases, project, remote, tmp_path):
    other = clone_of(remote, tmp_path / "other")
    git(other, "pull", "-q", "origin", "main")
    git(other, "tag", "v0.5.0")
    git(other, "push", "-q", "origin", "v0.5.0")
    commit_and_push(project)
    release(project, "patch")
    assert "v0.5.1" in tags_on(remote)


# --- What it does


def test_releasing_tags_head_pushes_the_tag_and_creates_the_github_release(
    releases, project, remote
):
    result = release(project, "minor")
    assert outcome.changes() == [
        "Tagged HEAD as v0.1.0",
        "Pushed v0.1.0",
        "Created the GitHub release v0.1.0",
    ]
    assert git(remote, "rev-parse", "v0.1.0^{commit}") == git(project, "rev-parse", "HEAD")
    assert git(project, "cat-file", "-t", "v0.1.0") == "tag", "an annotated tag"
    assert releases == ["me/thing@v0.1.0"]
    assert isinstance(result, Done)
    assert (result.summary, result.details) == (
        "Released v0.1.0.",
        ("https://github.com/me/thing/releases/tag/v0.1.0",),
    )


def test_releasing_a_commit_already_released_has_nothing_to_do(releases, project, remote):
    release(project, "minor")
    outcome.reset()
    result = release(project, "major")
    assert isinstance(result, NothingToDo)
    assert result.summary == "HEAD is already released as v0.1.0."
    assert tags_on(remote) == ["v0.1.0"]


def test_a_release_stopped_after_tagging_is_finished_on_running_again(releases, project, remote):
    git(project, "tag", "-a", "-m", "v0.1.0", "v0.1.0")
    release(project, "major")
    assert outcome.changes() == ["Pushed v0.1.0", "Created the GitHub release v0.1.0"]
    assert tags_on(remote) == ["v0.1.0"]


# --- What it refuses


def test_uncommitted_changes_are_refused(releases, project, remote):
    (project / "f").write_text("x\n")
    with pytest.raises(Precondition, match="Uncommitted changes"):
        release(project, "patch")
    assert tags_on(remote) == []


def test_commits_not_yet_pushed_are_refused(releases, project, remote):
    git(project, "commit", "-q", "--allow-empty", "-m", "local")
    with pytest.raises(Precondition, match="HEAD isn't on origin") as problem:
        release(project, "patch")
    assert problem.value.details == ("Push it first, so the release is of what's on GitHub.",)
    assert git(project, "tag") == ""


def test_a_detached_head_is_refused(releases, project):
    git(project, "checkout", "-q", "--detach")
    with pytest.raises(Precondition, match="HEAD is detached"):
        release(project, "patch")


def test_a_clone_without_an_origin_is_refused(releases, project):
    git(project, "remote", "remove", "origin")
    with pytest.raises(Precondition, match="No origin remote"):
        release(project, "patch")
