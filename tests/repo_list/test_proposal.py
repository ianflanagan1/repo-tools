"""Behaviour of opening pull requests where work goes by pull request, with the host faked."""

import subprocess
from pathlib import Path

import pytest

from repo_list import fix, hosts
from repo_list.hosts import NotOpened, Opened, Unknown, Visibility, proposal


class FakeHost:
    """A host whose answers are set, recording each pull request opened."""

    host = "GitHub"

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
def host(monkeypatch: pytest.MonkeyPatch) -> FakeHost:
    host = FakeHost()
    monkeypatch.setattr(hosts, "for_remote", lambda url: host)
    return host


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def pushed_feature(projects, *subjects: str) -> Path:
    """A repository on a branch, feature, with a commit of each subject, pushed to origin."""
    a = projects.pushed_repo("a")
    git(a, "checkout", "-qb", "feature")
    for subject in subjects:
        projects.commit(a, subject)
    git(a, "push", "-qu", "origin", "feature")
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
    projects, host, capsys
):
    projects.integration("pr-merge")
    pushed_feature(projects, "feature work")
    assert progress(capsys) == [
        "a",
        "  ✔ Opened a draft pull request for feature:",
        "    https://github.com/me/a/pull/1",
    ]
    assert host.opened == [("feature", "main", "feature work", "- feature work")]


def test_a_branch_with_a_pull_request_open_is_left_alone(projects, host, capsys):
    projects.integration("pr-rebase")
    pushed_feature(projects, "feature work")
    host.has_one = True
    assert progress(capsys) == []
    assert host.opened == []


def test_a_branch_pushed_in_the_same_run_gets_its_draft_then(projects, host, capsys):
    projects.integration("pr-merge")
    a = projects.pushed_repo("a")
    git(a, "checkout", "-qb", "feature")
    projects.commit(a, "feature work")
    assert progress(capsys) == [
        "a",
        "  ✔ Pushed feature to origin, now its upstream",
        "  ✔ Opened a draft pull request for feature:",
        "    https://github.com/me/a/pull/1",
    ]


def test_a_refused_pull_request_is_reported_with_what_the_host_said(projects, host, capsys):
    projects.integration("pr-merge")
    pushed_feature(projects, "feature work")
    host.refuses = True
    assert progress(capsys) == [
        "a",
        "  ✘ Opening a pull request for feature failed:",
        "    GitHub answered 403.",
    ]


def test_a_host_that_cannot_say_is_reported_with_why(projects, host, run):
    projects.integration("pr-merge")
    pushed_feature(projects, "feature work")
    host.has_one = Unknown("No GitHub token is stored.")
    assert run("--fetch").listing == [
        "🔀 ❔ 🔒 a  feature  ✘ 🔃 GitHub couldn't say if feature has a pull request: "
        "No GitHub token is stored."
    ]


def test_without_fetching_no_host_is_asked(projects, host, run):
    projects.integration("pr-merge")
    pushed_feature(projects, "feature work")
    assert run("-a").listing == ["🔀 ❔    a  feature  ✔"]


def test_a_branch_with_nothing_for_the_trunk_gets_no_pull_request(projects, host, capsys):
    projects.integration("pr-merge")
    pushed_feature(projects)
    assert progress(capsys) == []


def test_with_local_integration_no_pull_request_is_opened(projects, host, capsys):
    a = pushed_feature(projects, "feature work")
    progress(capsys)
    assert host.opened == []
    assert git(a, "rev-parse", "--abbrev-ref", "HEAD") == "feature"
