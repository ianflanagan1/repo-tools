"""bitbucket publish from start to finish, with Bitbucket's API replaced by a fake and its git
remote by a local bare repository, through git's url.<base>.insteadOf."""

import subprocess
from pathlib import Path

import pytest
from cli_kit import outcome
from cli_kit.outcome import Done, Failure, NothingToDo, Precondition

from repo_tools.bitbucket import api
from repo_tools.bitbucket.commands import publish as publish_module
from repo_tools.bitbucket.commands.publish import publish


def git(directory: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(directory), *args], check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(publish_module.time, "sleep", lambda seconds: None)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A committed, tagged project whose bitbucket.org remote URL leads to a local bare repo."""
    project = tmp_path / "Thing"
    remote = tmp_path / "remote.git"
    project.mkdir()
    git(tmp_path, "init", "--quiet", "--bare", str(remote))
    git(project, "init", "--quiet", "--initial-branch", "main")
    git(project, "config", "user.name", "t")
    git(project, "config", "user.email", "t@t")
    git(project, "config", f"url.{remote}.insteadOf", "git@bitbucket.org:team/thing.git")
    (project / "composer.json").write_text('{"description": "A thing"}')
    git(project, "add", "--all")
    git(project, "commit", "--quiet", "--message", "init")
    git(project, "tag", "v1.0.0")
    return project


def with_pipelines(project: Path) -> None:
    (project / "bitbucket-pipelines.yml").write_text("pipelines: {}\n")
    git(project, "add", "--all")
    git(project, "commit", "--quiet", "--message", "Add pipelines")


def test_publishing_creates_the_repo_in_the_workspace_with_a_lower_case_slug(bitbucket, project):
    result = publish(project, private=False, name=None, model=None)
    assert bitbucket.created == [("team/thing", False, "A thing", None)]
    assert isinstance(result, Done)
    assert (result.summary, result.details) == ("Published.", ("https://bitbucket.org/team/thing",))


def test_publishing_adds_origin_over_ssh_and_pushes_the_branch_and_tags(bitbucket, project):
    publish(project, private=False, name=None, model=None)
    assert git(project, "config", "remote.origin.url").strip() == "git@bitbucket.org:team/thing.git"
    assert git(project, "ls-remote", "--tags", "origin", "v1.0.0")


def test_a_project_key_puts_the_repo_in_that_project(bitbucket, project):
    publish(project, private=True, name=None, model=None, project="PROJ")
    assert bitbucket.created == [("team/thing", True, "A thing", "PROJ")]


def test_publishing_again_has_nothing_to_do(bitbucket, project):
    publish(project, private=False, name=None, model=None)
    outcome.reset()
    assert isinstance(publish(project, private=False, name=None, model=None), NothingToDo)


def test_an_existing_repo_of_other_visibility_stops_it_before_any_change(bitbucket, project):
    bitbucket.repos["team/thing"] = {"full_name": "team/thing", "is_private": True}
    with pytest.raises(Precondition, match="already exists and is private, not public"):
        publish(project, private=False, name=None, model=None)


def test_an_origin_naming_another_repo_stops_it(bitbucket, project):
    git(project, "remote", "add", "origin", "git@bitbucket.org:team/other.git")
    with pytest.raises(Precondition, match="origin is .* not team/thing"):
        publish(project, private=False, name=None, model=None)


def test_pipelines_is_turned_on_before_pushing_and_its_run_waited_for(bitbucket, project):
    with_pipelines(project)
    result = publish(project, private=False, name=None, model=None)
    assert bitbucket.pipelines_on == {"team/thing"}
    assert result.details[-1] == "Pipeline passed."


def test_a_failed_pipeline_fails_with_its_url_and_the_failed_steps_log(bitbucket, project):
    with_pipelines(project)
    bitbucket.pipeline_result = "FAILED"
    with pytest.raises(Failure) as failure:
        publish(project, private=False, name=None, model=None)
    assert "https://bitbucket.org/team/thing/pipelines/results/7" in failure.value.message
    assert failure.value.details == ("step 1", "boom")


def test_no_pipeline_starting_says_why(bitbucket, project):
    with_pipelines(project)
    bitbucket.pipeline_runs = False
    with pytest.raises(Failure, match="No pipeline started") as failure:
        publish(project, private=False, name=None, model=None)
    assert "push a new commit" in failure.value.details[0]


def test_no_ci_wait_skips_the_pipeline_but_still_turns_it_on(bitbucket, project):
    with_pipelines(project)
    bitbucket.pipeline_runs = False
    result = publish(project, private=False, name=None, model=None, wait_for_ci=False)
    assert bitbucket.pipelines_on == {"team/thing"}
    assert isinstance(result, Done)


def test_uncommitted_changes_stop_it_before_any_change(bitbucket, project):
    (project / "new.txt").write_text("x")
    with pytest.raises(Precondition, match="Uncommitted changes"):
        publish(project, private=False, name=None, model=None)
    assert bitbucket.created == []


class Model:
    """Replies with reply, and records each prompt and purpose."""

    def __init__(self, reply: str | None) -> None:
        self.answer = reply
        self.prompts: list[str] = []
        self.purposes: list[str] = []

    def reply(self, prompt: str, purpose: str) -> str | None:
        self.prompts.append(prompt)
        self.purposes.append(purpose)
        return self.answer


@pytest.fixture
def undescribed(project: Path) -> Path:
    """The project, with no description in its manifest."""
    (project / "composer.json").write_text("{}")
    (project / "README.md").write_text("# Thing\nSorts socks.\n")
    git(project, "add", "--all")
    git(project, "commit", "--quiet", "--message", "undescribe")
    return project


def test_a_description_in_the_manifest_is_used_without_asking_the_model(bitbucket, project):
    model = Model("Generated.")
    publish(project, private=False, name=None, model=model)
    assert bitbucket.created == [("team/thing", False, "A thing", None)]
    assert model.prompts == []


def test_without_a_manifest_description_the_model_writes_one(bitbucket, undescribed, capsys):
    model = Model("Sorts socks.")
    publish(undescribed, private=False, name=None, model=model)
    assert bitbucket.created == [("team/thing", False, "Sorts socks.", None)]
    assert "Repository: Thing" in model.prompts[0]
    assert "Generated its description: Sorts socks." in capsys.readouterr().out


def test_a_reply_over_the_limit_publishes_with_no_description(bitbucket, undescribed):
    model = Model("x" * (api.DESCRIPTION_MAX_LENGTH + 1))
    publish(undescribed, private=False, name=None, model=model)
    assert bitbucket.created == [("team/thing", False, "", None)]
