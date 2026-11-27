"""Behaviour of the icons repo-list shows after each path: the integration, and who can see
the remote repository."""

from pathlib import Path

import pytest

from repo_list import remote_repos
from repo_list.git_hosts import GitHost, Visibility
from repo_list.remote_repos import Unknown


class FakeRemoteRepo:
    git_host = GitHost.GITHUB

    def __init__(self, visibility: Visibility | Unknown) -> None:
        self.answer = visibility
        self.asked = 0

    def visibility(self) -> Visibility | Unknown:
        self.asked += 1
        return self.answer


@pytest.fixture
def remote_repo(monkeypatch: pytest.MonkeyPatch):
    """Makes every remote repo answer as given."""

    def remote_repo(visibility: Visibility | Unknown) -> FakeRemoteRepo:
        fake = FakeRemoteRepo(visibility)
        monkeypatch.setattr(remote_repos, "for_remote", lambda url: fake)
        return fake

    return remote_repo


def test_a_public_repository_shows_the_globe_once_fetched(projects, run, remote_repo):
    projects.pushed_repo("a")
    remote_repo(Visibility.PUBLIC)
    assert run("--fetch", "--all").listing == ["🏠 ❔ 🌐 a  main  ✔"]


def test_a_private_repository_shows_the_padlock_once_fetched(projects, run, remote_repo):
    projects.pushed_repo("a")
    remote_repo(Visibility.PRIVATE)
    assert run("--fetch", "--all").listing == ["🏠 ❔ 🔒 a  main  ✔"]


def test_without_fetching_the_git_host_is_not_asked_and_the_slot_is_blank(
    projects, run, remote_repo
):
    projects.pushed_repo("a")
    fake = remote_repo(Visibility.PUBLIC)
    assert run("--all").listing == ["🏠 ❔    a  main  ✔"]
    assert fake.asked == 0


def test_a_git_host_that_cannot_say_leaves_the_slot_blank(projects, run, remote_repo):
    projects.pushed_repo("a")
    remote_repo(Unknown("No GitHub token is stored."))
    assert run("--fetch", "--all").listing == ["🏠 ❔    a  main  ✔"]


def test_a_linked_worktree_shows_the_remotes_icons_as_its_main_worktree_does(
    projects, run, remote_repo
):
    a = projects.pushed_repo("a")
    projects.worktree(a, "a-wt", "-b", "feature")
    remote_repo(Visibility.PUBLIC)
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


def test_a_dependency_shows_its_kind_after_the_visibility(projects, run):
    projects.package("a")
    projects.pushed_repo("b")
    assert run("--all").listing == [
        "🏠 ❔    🐘 a  main  ✔",
        "🏠 ❔       b  main  ✔",
    ]


def test_without_a_dependency_listed_there_is_no_dependency_column(projects, run):
    projects.pushed_repo("a")
    assert run("--all").listing == ["🏠 ❔    a  main  ✔"]


def test_a_dependency_of_another_vendor_still_shows_its_kind(projects, run):
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


def test_a_python_project_other_repositories_read_from_a_path_is_no_dependency(projects, run):
    projects.python_project("kit", KIT)
    projects.python_project("tools", uses_kit('{ path = "../kit", editable = true }'))
    assert run("--all").listing == ["🏠 ❔    kit    main  ✔", "🏠 ❔    tools  main  ✔"]


def settings_making_origin(projects, repo: Path, visibility: str) -> None:
    """Commits and pushes settings that make origin visibility, and gives origin a GitHub URL,
    which git config sends to its bare repository."""
    (repo / ".config" / "ianf-repo-tools.toml").write_text(
        f'version = 1\nintegration = "direct"\n\n[remotes.origin]\ngit-host = "github"\n'
        f'visibility = "{visibility}"\n'
    )
    projects.git("-C", repo, "commit", "--quiet", "--all", "--message", "Settings")
    projects.git("-C", repo, "push", "--quiet")
    url = "git@github.com:me/a.git"
    projects.git("-C", repo, "config", f"url.{projects.origin(repo)}.insteadOf", url)
    projects.git("-C", repo, "remote", "set-url", "origin", url)


def test_origin_seen_by_who_its_settings_say_is_clean(projects, run, remote_repo):
    a = projects.pushed_repo("a")
    settings_making_origin(projects, a, "private")
    remote_repo(Visibility.PRIVATE)
    assert run("--fetch", "--all").listing == ["🏠 🐙 🔒 a  main  ✔"]


def test_origin_seen_by_others_than_its_settings_say_is_reported(projects, run, remote_repo):
    a = projects.pushed_repo("a")
    settings_making_origin(projects, a, "private")
    remote_repo(Visibility.PUBLIC)
    assert run("--fetch").listing == [
        "🏠 🐙 🌐 a  main  ✘ 🧭 origin is public, though .config/ianf-repo-tools.toml makes it"
        " private"
    ]
