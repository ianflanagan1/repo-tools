"""Behaviour of opening pull requests where work goes by pull request, with the remote repo
faked."""

import subprocess
from pathlib import Path

import pytest

from repo_list import fix, remote_repos
from repo_list.git_hosts import GitHost
from repo_list.remote_repos import NotOpened, Opened, Unknown, Visibility, proposal


class FakeRemoteRepo:
    """A remote repo whose answers are set, recording each pull request opened."""

    git_host = GitHost.GITHUB

    def __init__(self) -> None:
        self.has_one: bool | Unknown = False
        self.refuses = False
        self.opened: list[tuple[str, str, str, str]] = []

    def visibility(self) -> Visibility | Unknown:
        return Visibility.PRIVATE

    def open_for(self, branch: str) -> bool | Unknown:
        return self.has_one

    def open_draft(self, branch: str, base: str, title: str, body: str) -> Opened | NotOpened:
        if self.refuses:
            return NotOpened(("GitHub answered 403.",))
        self.opened.append((branch, base, title, body))
        return Opened(f"https://github.com/me/a/pull/{len(self.opened)}")


@pytest.fixture
def remote_repo(monkeypatch: pytest.MonkeyPatch) -> FakeRemoteRepo:
    remote_repo = FakeRemoteRepo()
    monkeypatch.setattr(remote_repos, "for_remote", lambda url: remote_repo)
    return remote_repo


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def pushed_feature(projects, *subjects: str) -> Path:
    """A repository on a branch, feature, with a commit of each subject, pushed to origin."""
    a = projects.pushed_repo("a")
    git(a, "checkout", "--quiet", "-b", "feature")
    for subject in subjects:
        projects.commit(a, subject)
    git(a, "push", "--quiet", "--set-upstream", "origin", "feature")
    return a


def progress(capsys, *args: str) -> list[str]:
    fix.main(list(args))
    out = capsys.readouterr().out
    return out.split("\n\n")[0].splitlines() if out.startswith("a\n") else []


# --- The pull request's title and body


def test_one_commit_gives_the_pull_request_its_subject_as_title():
    assert proposal("feature", ["Add the thing"]) == ("Add the thing", "- Add the thing")


def test_several_commits_give_it_the_branch_as_title_and_list_their_subjects():
    title, body = proposal("feature", ["One", "Two"])
    assert (title, body) == ("feature", "- One\n- Two")


# --- Opening one


def test_with_pr_integration_a_pushed_branch_without_a_pull_request_gets_a_draft(
    projects, remote_repo, capsys
):
    projects.integration("pr-merge")
    pushed_feature(projects, "feature work")
    assert progress(capsys) == [
        "a",
        "  ✔ Opened a draft pull request for feature:",
        "    https://github.com/me/a/pull/1",
    ]
    assert remote_repo.opened == [("feature", "main", "feature work", "- feature work")]


def test_a_branch_with_a_pull_request_open_is_left_alone(projects, remote_repo, capsys):
    projects.integration("pr-rebase")
    pushed_feature(projects, "feature work")
    remote_repo.has_one = True
    assert progress(capsys) == []
    assert remote_repo.opened == []


def test_a_branch_pushed_in_the_same_run_gets_its_draft_then(projects, remote_repo, capsys):
    projects.integration("pr-merge")
    a = projects.pushed_repo("a")
    git(a, "checkout", "--quiet", "-b", "feature")
    projects.commit(a, "feature work")
    assert progress(capsys) == [
        "a",
        "  ✔ Pushed feature to origin, now its upstream",
        "  ✔ Opened a draft pull request for feature:",
        "    https://github.com/me/a/pull/1",
    ]


def test_a_refused_pull_request_is_reported_with_what_the_git_host_said(
    projects, remote_repo, capsys
):
    projects.integration("pr-merge")
    pushed_feature(projects, "feature work")
    remote_repo.refuses = True
    assert progress(capsys) == [
        "a",
        "  ✘ Opening a pull request for feature failed:",
        "    GitHub answered 403.",
    ]


def test_a_git_host_that_cannot_say_is_reported_with_why(projects, remote_repo, run):
    projects.integration("pr-merge")
    pushed_feature(projects, "feature work")
    remote_repo.has_one = Unknown("No GitHub token is stored.")
    assert run("--fetch").listing == [
        "🔀 ❔ 🔒 a  feature  ✘ 🔃 GitHub couldn't say if feature has a pull request: "
        "No GitHub token is stored."
    ]


def test_without_fetching_no_git_host_is_asked(projects, remote_repo, run):
    projects.integration("pr-merge")
    pushed_feature(projects, "feature work")
    assert run("--all").listing == ["🔀 ❔    a  feature  ✔"]


def test_a_branch_with_nothing_for_the_trunk_gets_no_pull_request(projects, remote_repo, capsys):
    projects.integration("pr-merge")
    pushed_feature(projects)
    assert progress(capsys) == []


def test_with_local_integration_no_pull_request_is_opened(projects, remote_repo, capsys):
    a = pushed_feature(projects, "feature work")
    progress(capsys)
    assert remote_repo.opened == []
    assert git(a, "rev-parse", "--abbrev-ref", "HEAD") == "feature"
