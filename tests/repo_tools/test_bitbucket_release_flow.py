"""bitbucket release from start to finish, with the Bitbucket remote a local bare repository."""

import subprocess
from pathlib import Path

import pytest
from cli_kit import outcome
from cli_kit.outcome import Done, NothingToDo, Precondition

from repo_tools.bitbucket.commands.release import release


def git(directory: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(directory), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def clone(tmp_path: Path) -> Path:
    """A clone whose HEAD is on its bitbucket.org origin, a local bare repo, tagged v1.2.0."""
    remote, clone = tmp_path / "remote.git", tmp_path / "clone"
    clone.mkdir()
    git(tmp_path, "init", "--quiet", "--bare", str(remote))
    git(clone, "init", "--quiet", "--initial-branch", "main")
    git(clone, "config", "user.name", "t")
    git(clone, "config", "user.email", "t@t")
    git(clone, "config", f"url.{remote}.insteadOf", "git@bitbucket.org:team/thing.git")
    git(clone, "remote", "add", "origin", "git@bitbucket.org:team/thing.git")
    git(clone, "commit", "--quiet", "--allow-empty", "--message", "one")
    git(clone, "tag", "v1.2.0")
    git(clone, "commit", "--quiet", "--allow-empty", "--message", "two")
    git(clone, "push", "--quiet", "origin", "main", "--tags")
    outcome.reset()
    return clone


def test_tags_head_as_the_next_version_and_pushes_the_tag(clone):
    result = release(clone, "minor")
    assert outcome.changes() == ["Tagged HEAD as v1.3.0", "Pushed v1.3.0"]
    assert git(clone, "ls-remote", "--tags", "origin", "v1.3.0")
    assert isinstance(result, Done)
    assert result.details == ("https://bitbucket.org/team/thing/src/v1.3.0",)


def test_releasing_a_released_head_again_has_nothing_to_do(clone):
    release(clone, "patch")
    outcome.reset()
    assert isinstance(release(clone, "major"), NothingToDo)


def test_a_head_not_on_origin_stops_it(clone):
    git(clone, "commit", "--quiet", "--allow-empty", "--message", "three")
    with pytest.raises(Precondition, match="HEAD isn't on origin"):
        release(clone, "patch")


def test_an_origin_not_on_bitbucket_stops_it(clone):
    git(clone, "remote", "set-url", "origin", "git@github.com:me/thing.git")
    with pytest.raises(Precondition, match="not a Bitbucket repo"):
        release(clone, "patch")
