"""Behaviour of the icons repo-list shows after each path: the integration mode, and who can see
the remote repository."""

import pytest

from repo_list import hosts
from repo_list.hosts import Unknown, Visibility


class FakeHost:
    host = "GitHub"

    def __init__(self, visibility: Visibility | Unknown) -> None:
        self.answer = visibility
        self.asked = 0

    def visibility(self) -> Visibility | Unknown:
        self.asked += 1
        return self.answer


@pytest.fixture
def host(monkeypatch: pytest.MonkeyPatch):
    """Makes every remote's host answer as given."""

    def host(visibility: Visibility | Unknown) -> FakeHost:
        fake = FakeHost(visibility)
        monkeypatch.setattr(hosts, "for_remote", lambda url: fake)
        return fake

    return host


def test_a_public_repository_shows_the_globe_once_fetched(projects, run, host):
    projects.pushed_repo("a")
    host(Visibility.PUBLIC)
    assert run("--fetch", "-a").listing == ["✔ 🏠 ❔ 🌐 a  main"]


def test_a_private_repository_shows_the_padlock_once_fetched(projects, run, host):
    projects.pushed_repo("a")
    host(Visibility.PRIVATE)
    assert run("--fetch", "-a").listing == ["✔ 🏠 ❔ 🔒 a  main"]


def test_without_fetching_the_host_is_not_asked_and_the_slot_is_blank(projects, run, host):
    projects.pushed_repo("a")
    fake = host(Visibility.PUBLIC)
    assert run("-a").listing == ["✔ 🏠 ❔    a  main"]
    assert fake.asked == 0


def test_a_host_that_cannot_say_leaves_the_slot_blank(projects, run, host):
    projects.pushed_repo("a")
    host(Unknown("No GitHub token is stored."))
    assert run("--fetch", "-a").listing == ["✔ 🏠 ❔    a  main"]


def test_a_linked_worktree_leaves_both_icons_to_its_main_worktree(projects, run, host):
    a = projects.pushed_repo("a")
    projects.worktree(a, "a-wt", "-b", "feature")
    host(Visibility.PUBLIC)
    assert run("--fetch", "-a").listing == ["✔ 🏠 ❔ 🌐 a     main", "✔          a-wt  feature"]


def test_a_linked_worktree_whose_own_mode_differs_shows_it(projects, run):
    a = projects.pushed_repo("a")
    wt = projects.worktree(a, "a-wt", "-b", "feature")
    (wt / ".workspace.toml").write_text('[repo-tools]\nintegration = "pr-merge"\n')
    projects.git("-C", wt, "commit", "-qam", "pr-merge here")
    assert run("-a").listing == [
        "✔ 🏠 ❔    a     main",
        "✘ 🔀       a-wt  feature  📤 1 unpushed on feature",
    ]


@pytest.mark.parametrize(
    ("mode", "icon"), [("local", "🏠"), ("pr-rebase", "📏"), ("pr-merge", "🔀")]
)
def test_each_mode_shows_its_icon(projects, run, mode, icon):
    projects.integration(mode)
    projects.pushed_repo("a")
    assert run("-a").listing == [f"✔ {icon} ❔    a  main"]
