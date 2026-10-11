"""github publish from start to finish, with GitHub replaced: gh calls by fakes, and the
GitHub remote by a local bare repository, through git's url.<base>.insteadOf."""

import subprocess
from pathlib import Path

import pytest
from cli_kit import outcome
from cli_kit.errors import Precondition
from cli_kit.outcome import Done, NothingToDo

from repo_tools.github import api
from repo_tools.github.__main__ import main
from repo_tools.github.commands import publish as publish_module
from repo_tools.github.commands.publish import publish


def git(directory: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(directory), *args], check=True, capture_output=True, text=True
    ).stdout


class GitHub:
    """What the fakes know: which repos exist, and the repos created."""

    def __init__(self) -> None:
        self.repos: dict[str, str] = {}
        self.created: list[tuple[str, str, str]] = []


@pytest.fixture
def github(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> GitHub:
    github = GitHub()

    def create(repo: str, visibility: str, description: str) -> None:
        github.created.append((repo, visibility, description))
        github.repos[repo] = visibility

    monkeypatch.setattr(api, "current_user", lambda: "me")
    monkeypatch.setattr(api, "exists", lambda repo: repo in github.repos)
    monkeypatch.setattr(api, "visibility", lambda repo: github.repos[repo])
    monkeypatch.setattr(api, "create", create)
    outcome.reset()
    return github


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A committed, tagged project whose github.com remote URL leads to a local bare repo."""
    project = tmp_path / "thing"
    remote = tmp_path / "remote.git"
    project.mkdir()
    git(tmp_path, "init", "-q", "--bare", str(remote))
    git(project, "init", "-q", "-b", "main")
    git(project, "config", "user.name", "t")
    git(project, "config", "user.email", "t@t")
    git(project, "config", f"url.{remote}.insteadOf", "git@github.com:me/thing.git")
    (project / "composer.json").write_text('{"description": "A thing"}')
    git(project, "add", "-A")
    git(project, "commit", "-qm", "init")
    git(project, "tag", "v1.0.0")
    return project


def test_publishing_a_new_project_creates_the_repo_adds_origin_and_pushes(github, project):
    result = publish(project, "public", None)
    assert github.created == [("me/thing", "public", "A thing")]
    assert outcome.changes() == [
        "Created me/thing (public)",
        "Added origin me/thing",
        "Pushed main",
        "Pushed tags",
    ]
    assert isinstance(result, Done)
    assert (result.summary, result.details) == ("Published.", ("https://github.com/me/thing",))


def test_with_no_arguments_the_current_directory_is_published_as_public(
    github, project, monkeypatch
):
    monkeypatch.chdir(project)
    assert main(["publish"]) == 0
    assert github.created == [("me/thing", "public", "A thing")]


def test_the_private_flag_creates_a_private_repo(github, project):
    assert main(["publish", str(project), "--private"]) == 0
    assert github.created == [("me/thing", "private", "A thing")]


def test_a_repo_name_after_the_directory_names_the_repo(github, project):
    remote = project.parent / "remote.git"
    git(project, "config", f"url.{remote}.insteadOf", "git@github.com:me/other.git")
    assert main(["publish", str(project), "other"]) == 0
    assert github.created == [("me/other", "public", "A thing")]


def test_publishing_again_has_nothing_to_do(github, project):
    publish(project, "public", None)
    outcome.reset()
    result = publish(project, "public", None)
    assert isinstance(result, NothingToDo)
    assert result.summary == "Already published: https://github.com/me/thing"


def test_a_new_commit_is_pushed_on_publishing_again(github, project):
    publish(project, "public", None)
    outcome.reset()
    git(project, "commit", "-q", "--allow-empty", "-m", "more")
    assert isinstance(publish(project, "public", None), Done)
    assert outcome.changes() == ["Pushed main"]


def test_an_origin_for_another_repo_stops_it_before_creating_anything(github, project):
    git(project, "remote", "add", "origin", "git@github.com:someone/else.git")
    with pytest.raises(Precondition, match="origin is git@github.com:someone/else.git"):
        publish(project, "public", None)
    assert github.created == []


def test_an_existing_repo_with_the_other_visibility_is_left_alone(github, project):
    github.repos["me/thing"] = "private"
    with pytest.raises(Precondition, match="already exists and is private, not public"):
        publish(project, "public", None)
    assert outcome.changes() == []


@pytest.fixture
def ci_waits(project: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Gives the project a CI workflow, and records each wait for a CI run instead of waiting."""
    workflows = project / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text("on: push\n")
    git(project, "add", "-A")
    git(project, "commit", "-qm", "ci")
    waits: list[str] = []
    monkeypatch.setattr(publish_module, "_wait_for_ci", lambda repo, commit: waits.append(repo))
    return waits


def test_a_project_with_a_workflow_waits_for_its_ci_run(github, project, ci_waits, capsys):
    assert main(["publish", str(project)]) == 0
    assert ci_waits == ["me/thing"]
    assert capsys.readouterr().out.endswith("CI passed.\n")


def test_the_no_ci_wait_flag_publishes_without_waiting_for_ci(github, project, ci_waits, capsys):
    assert main(["publish", str(project), "--no-ci-wait"]) == 0
    assert ci_waits == []
    assert "CI passed." not in capsys.readouterr().out
