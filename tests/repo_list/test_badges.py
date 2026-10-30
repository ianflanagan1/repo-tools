"""Behaviour of the icons repo-list shows after each path: the integration, and who can see
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
    assert run("--fetch", "--all").listing == ["🏠 ❔ 🌐 a  main  ✔"]


def test_a_private_repository_shows_the_padlock_once_fetched(projects, run, host):
    projects.pushed_repo("a")
    host(Visibility.PRIVATE)
    assert run("--fetch", "--all").listing == ["🏠 ❔ 🔒 a  main  ✔"]


def test_without_fetching_the_host_is_not_asked_and_the_slot_is_blank(projects, run, host):
    projects.pushed_repo("a")
    fake = host(Visibility.PUBLIC)
    assert run("--all").listing == ["🏠 ❔    a  main  ✔"]
    assert fake.asked == 0


def test_a_host_that_cannot_say_leaves_the_slot_blank(projects, run, host):
    projects.pushed_repo("a")
    host(Unknown("No GitHub token is stored."))
    assert run("--fetch", "--all").listing == ["🏠 ❔    a  main  ✔"]


def test_a_linked_worktree_shows_the_remotes_icons_as_its_main_worktree_does(projects, run, host):
    a = projects.pushed_repo("a")
    projects.worktree(a, "a-wt", "-b", "feature")
    host(Visibility.PUBLIC)
    assert run("--fetch", "--all").listing == [
        "🏠 ❔ 🌐 a     main     ✔",
        "🏠 ❔ 🌐 a-wt  feature  ✔",
    ]


def test_a_linked_worktree_whose_own_integration_differs_shows_it(projects, run):
    a = projects.pushed_repo("a")
    wt = projects.worktree(a, "a-wt", "-b", "feature")
    (wt / ".config" / "ianf-repo-tools.toml").write_text('version = 1\nintegration = "pr-merge"\n')
    projects.git("-C", wt, "commit", "--quiet", "--all", "--message", "pr-merge here")
    assert run("--all").listing == [
        "🏠 ❔    a     main     ✔",
        "🔀 ❔    a-wt  feature  ✘ 📤 1 unpushed on feature",
    ]


@pytest.mark.parametrize(
    ("integration", "icon"), [("direct", "🏠"), ("pr-rebase", "📏"), ("pr-merge", "🔀")]
)
def test_each_integration_shows_its_icon(projects, run, integration, icon):
    projects.integration(integration)
    projects.pushed_repo("a")
    assert run("--all").listing == [f"{icon} ❔    a  main  ✔"]


def test_a_package_shows_its_kind_after_the_visibility(projects, run):
    projects.package("a")
    projects.pushed_repo("b")
    assert run("--all").listing == [
        "🏠 ❔    🐘 a  main  ✔",
        "🏠 ❔       b  main  ✔",
    ]


def test_without_a_package_listed_there_is_no_package_column(projects, run):
    projects.pushed_repo("a")
    assert run("--all").listing == ["🏠 ❔    a  main  ✔"]


def test_a_package_of_another_vendor_still_shows_its_kind(projects, run):
    projects.package("a", vendor="someone")
    assert run("--all").listing == ["🏠 ❔    🐘 a  main  ✔"]


def test_a_repository_that_is_several_kinds_shows_each_and_widens_the_column(projects, run):
    a = projects.npm_package("a", {"name": "a"})
    (a / "copier.yml").write_text("")
    projects.git("-C", a, "add", "--all")
    projects.git("-C", a, "commit", "--quiet", "--message", "copier.yml")
    projects.git("-C", a, "push", "--quiet")
    projects.package("b")
    assert run("--all").listing == [
        "🏠 ❔    🔴📋 a  main  ✔",
        "🏠 ❔    🐘   b  main  ✔",
    ]


def test_a_linked_worktree_shows_its_kind_as_its_main_worktree_does(projects, run):
    a = projects.package("a")
    projects.worktree(a, "a-wt", "-b", "feature")
    assert run("--all").listing == [
        "🏠 ❔    🐘 a     main     ✔",
        "🏠 ❔    🐘 a-wt  feature  ✔",
    ]


def test_a_linked_worktree_whose_branch_makes_it_another_kind_shows_it(projects, run):
    a = projects.package("a")
    wt = projects.worktree(a, "a-wt", "-b", "feature")
    (wt / "package.json").write_text('{"name": "a"}')
    assert run("--all").listing == [
        "🏠 ❔    🐘   a     main     ✔",
        "🏠 ❔    🐘🔴 a-wt  feature  ✘ 📝 1 uncommitted file",
    ]


KIT = '[project]\nname = "kit"\n\n[build-system]\nbuild-backend = "uv_build"\n'


def uses_kit(source: str) -> str:
    return (
        '[project]\nname = "tools"\ndependencies = ["kit"]\n\n'
        '[build-system]\nbuild-backend = "uv_build"\n\n'
        f"[tool.uv.sources]\nkit = {source}\n"
    )


def test_a_python_project_another_repository_pins_from_git_is_a_python_package(projects, run):
    projects.python_project("kit", KIT)
    projects.python_project("tools", uses_kit('{ git = "https://example.com/kit" }'))
    assert run("--all").listing == [
        "🏠 ❔    🐍 kit    main  ✔",
        "🏠 ❔       tools  main  ✔",
    ]


def test_a_python_project_other_repositories_read_from_a_path_is_no_package(projects, run):
    projects.python_project("kit", KIT)
    projects.python_project("tools", uses_kit('{ path = "../kit", editable = true }'))
    assert run("--all").listing == ["🏠 ❔    kit    main  ✔", "🏠 ❔    tools  main  ✔"]
