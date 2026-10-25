"""Generating a repository's description from its tracked files, with the model replaced."""

import subprocess
from pathlib import Path

import pytest
from cli_kit import models, outcome
from cli_kit.models import Provider

from repo_list import config
from repo_list.config import Config
from repo_tools.description import configured_model, for_new_repo, generate


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


def git(directory: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(directory), *args], check=True, capture_output=True)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "README.md").write_text("# Thing\nSorts socks.\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "sort.py").write_text("")
    (tmp_path / "src" / "README.md").write_text("Nested readme")
    git(tmp_path, "add", "-A")
    return tmp_path


def test_the_model_is_shown_the_tracked_files_and_top_level_readme(project):
    model = Model("Sorts socks.")
    assert generate(project, "thing", model, 350) == "Sorts socks."
    [prompt] = model.prompts
    assert "Repository: thing" in prompt
    assert "README.md\nsrc/README.md\nsrc/sort.py" in prompt
    assert "--- README.md ---\n# Thing\nSorts socks." in prompt
    assert "Nested readme" not in prompt


def test_untracked_files_are_never_shown_to_the_model(project):
    (project / ".env").write_text("SECRET=1")
    (project / "CLAUDE.md").write_text("untracked notes")
    model = Model("Sorts socks.")
    generate(project, "thing", model, 350)
    [prompt] = model.prompts
    assert ".env" not in prompt
    assert "untracked notes" not in prompt


def test_a_model_that_cannot_reply_gives_no_description(project):
    assert generate(project, "thing", Model(None), 350) is None


def test_a_reply_over_the_limit_gives_no_description(project):
    assert generate(project, "thing", Model("x" * 351), 350) is None


def test_a_repository_with_no_tracked_files_is_not_sent_to_the_model(tmp_path: Path):
    git(tmp_path, "init", "-q", "-b", "main")
    model = Model("Anything.")
    assert generate(tmp_path, "thing", model, 350) is None
    assert model.prompts == []


def test_a_new_repo_takes_its_manifests_description_without_asking_the_model(project):
    (project / "package.json").write_text('{"description": "A sock sorter"}')
    model = Model("Sorts socks.")
    assert for_new_repo(project, "thing", model, 350) == "A sock sorter"
    assert model.prompts == []


def test_a_new_repo_without_one_takes_the_models_and_says_so(project, capsys):
    assert for_new_repo(project, "thing", Model("Sorts socks."), 350) == "Sorts socks."
    assert capsys.readouterr().out == "Generated its description: Sorts socks.\n"


def test_a_new_repo_with_no_model_and_no_manifest_description_has_none(project):
    assert for_new_repo(project, "thing", None, 350) == ""


def test_a_new_repo_whose_model_gives_nothing_usable_has_none(project, capsys):
    assert for_new_repo(project, "thing", Model(None), 350) == ""
    assert capsys.readouterr().out == ""


def test_the_configured_providers_small_model_writes(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "load", lambda: Config(description_provider=Provider.GEMINI))
    assert configured_model() == models.small(Provider.GEMINI, outcome.starting)


def test_the_model_is_asked_with_the_purpose_to_announce(project: Path):
    model = Model("Sorts socks.")
    generate(project, "thing", model, 350)
    assert model.purposes == ["Writing a description for thing"]


def test_with_no_configured_provider_no_model_writes(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "load", lambda: Config(description_provider=None))
    assert configured_model() is None
