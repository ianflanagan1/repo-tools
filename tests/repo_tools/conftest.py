"""Fixtures shared by the bitbucket command tests."""

import pytest
from cli_kit import outcome

from repo_list import config
from repo_list.config import Config
from repo_tools.bitbucket import api


class FakeBitbucket:
    """Bitbucket's repos and pipelines, as the commands see them through the API client."""

    def __init__(self) -> None:
        self.repos: dict[str, dict] = {}
        self.created: list[tuple] = []
        self.renamed: list[tuple[str, str]] = []
        self.deleted: list[str] = []
        self.pipelines_on: set[str] = set()
        self.pipeline_result = "SUCCESSFUL"
        self.pipeline_runs = True
        self.redirects: dict[str, str] = {}

    def repository(self, repo: str) -> dict | None:
        repo = self.redirects.get(repo, repo)
        return self.repos.get(repo)

    def create(self, repo, private, description, project) -> None:
        self.created.append((repo, private, description, project))
        self.repos[repo] = {"full_name": repo, "is_private": private}

    def rename(self, repo: str, new_name: str) -> str:
        new = f"{repo.split('/')[0]}/{new_name.lower()}"
        self.renamed.append((repo, new_name))
        self.repos[new] = {**self.repos.pop(repo), "full_name": new}
        self.redirects[repo] = new
        return new

    def delete(self, repo: str) -> None:
        self.deleted.append(repo)

    def pipelines_enabled(self, repo: str) -> bool:
        return repo in self.pipelines_on

    def enable_pipelines(self, repo: str) -> None:
        self.pipelines_on.add(repo)

    def pipeline_for(self, repo: str, commit: str) -> dict | None:
        if not self.pipeline_runs:
            return None
        return {"uuid": "{p}", "build_number": 7, "state": {"name": "IN_PROGRESS"}}

    def pipeline(self, repo: str, uuid: str) -> dict:
        return {
            "uuid": uuid,
            "build_number": 7,
            "state": {"name": "COMPLETED", "result": {"name": self.pipeline_result}},
        }

    def failed_step_log(self, repo: str, pipeline: str) -> str:
        return "step 1\nboom\n"


@pytest.fixture
def bitbucket(monkeypatch: pytest.MonkeyPatch) -> FakeBitbucket:
    """A fake Bitbucket in the configured workspace team, which no command can sign in past."""
    fake = FakeBitbucket()
    monkeypatch.setattr(api, "connect", lambda: fake)
    monkeypatch.setattr(config, "load", lambda: Config(bitbucket_workspace="team"))
    outcome.reset()
    return fake
