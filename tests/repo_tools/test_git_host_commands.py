"""The delivery commands every git host's tool lists, run against a fake GitHostApi."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from repo_tools import git_host_commands
from repo_tools.bitbucket.__main__ import main as bitbucket
from repo_tools.git_host_api import Commit, Deployment, GitHostApi, PullRequest, Status
from repo_tools.github.__main__ import main as github

T = datetime(2026, 9, 1, 12, tzinfo=UTC)


class FakeGitHostApi(GitHostApi):
    name = "Fake"

    def __init__(self) -> None:
        self.asked: list[tuple] = []

    def full_name(self, repo: str) -> str:
        return repo if "/" in repo else f"me/{repo}"

    def url(self, repo: str) -> str:
        return f"git@fake.example:{repo}.git"

    def main_branch(self, repo: str) -> str:
        return "main"

    def file(self, repo: str, revision: str, path: str) -> str | None:
        return None

    def environments(self, repo: str) -> list[str]:
        return ["production"]

    def deployments(self, repo, environment, since):
        self.asked.append(("deployments", repo, environment, since))
        return [Deployment("1", "production", "a" * 40, Status.SUCCEEDED, T, T, "https://x/1")]

    def merged_pull_requests(self, repo, since, base=None):
        self.asked.append(("merged", repo, since, base))
        return [PullRequest(3, "Fix", "me", "main", T, T, "b" * 40, "https://x/3")]

    def commits_between(self, repo, base, head):
        self.asked.append(("commits", repo, base, head))
        return [Commit("c" * 40, T, "Fix it", merge=False)]


@pytest.fixture
def git_host(monkeypatch: pytest.MonkeyPatch) -> FakeGitHostApi:
    fake = FakeGitHostApi()
    for tool in ("github", "bitbucket"):
        module = __import__(f"repo_tools.{tool}.__main__", fromlist=["COMMANDS"])
        commands = [c for c in module.COMMANDS if not isinstance(c, git_host_commands.Command)]
        monkeypatch.setattr(
            module, "COMMANDS", [*commands, *git_host_commands.commands(lambda: fake)]
        )
    return fake


def data(output: str) -> list[dict]:
    return [json.loads(line) for line in output.splitlines() if line.startswith("{")]


@pytest.mark.parametrize("main", [github, bitbucket])
def test_every_git_host_lists_the_same_delivery_commands(main, capsys):
    main(["help"])
    listing = capsys.readouterr().out
    for command in ("url", "environments", "deployments", "merged", "commits"):
        assert f"  {command} " in listing or f"  {command}\n" in listing


def test_prints_each_deployment_as_a_json_line_then_the_status_line(git_host, capsys):
    assert github(["deployments", "me/app", "production", "--since", "2026-08-01"]) == 0
    out = capsys.readouterr().out
    assert data(out) == [
        {
            "id": "1",
            "environment": "production",
            "commit": "a" * 40,
            "status": "succeeded",
            "started_at": "2026-09-01T12:00:00+00:00",
            "finished_at": "2026-09-01T12:00:00+00:00",
            "url": "https://x/1",
        }
    ]
    assert out.splitlines()[-1] == "➖ 1 deployment of me/app to production since 2026-08-01."


def test_url_prints_the_repo_and_its_url_as_a_json_line_then_the_status_line(git_host, capsys):
    assert github(["url", "app"]) == 0
    out = capsys.readouterr().out
    assert data(out) == [{"repo": "me/app", "url": "git@fake.example:me/app.git"}]
    assert out.splitlines()[-1] == "➖ me/app is at git@fake.example:me/app.git."


def test_a_bare_repo_name_is_given_the_hosts_default_owner(git_host):
    bitbucket(["commits", "app", "v1", "v2"])
    assert git_host.asked == [("commits", "me/app", "v1", "v2")]


def test_merged_passes_the_base_branch_on(git_host, capsys):
    bitbucket(["merged", "me/app", "--base", "main", "--since", "2026-08-01"])
    assert git_host.asked[0][3] == "main"
    assert data(capsys.readouterr().out)[0]["merge_commit"] == "b" * 40


def test_since_is_thirty_days_ago_unless_given(git_host):
    github(["deployments", "me/app", "production"])
    since = git_host.asked[0][3]
    assert abs(datetime.now(UTC) - timedelta(days=30) - since) < timedelta(minutes=1)


def test_since_takes_a_date_as_midnight_utc():
    assert git_host_commands.parse_since("2026-07-01") == datetime(2026, 7, 1, tzinfo=UTC)


def test_since_takes_a_time_with_its_offset_converted_to_utc():
    assert git_host_commands.parse_since("2026-07-01T09:00+01:00") == datetime(
        2026, 7, 1, 8, tzinfo=UTC
    )


def test_since_that_is_not_a_date_is_a_usage_error(git_host, capsys):
    with pytest.raises(SystemExit) as exit:
        github(["deployments", "me/app", "production", "--since", "last week"])
    assert exit.value.code == 2
    assert "isn't a date" in capsys.readouterr().err
