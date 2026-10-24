"""Behaviour of the scan's running of the plugins' checks, with the plugins faked."""

from pathlib import Path

from repo_list import scan
from repo_list.integration import Worktree
from repo_list.scan import Directory


def described(directory: Directory) -> list[str]:
    return [p.describe() for p in directory.problems]


def test_problems_are_in_the_plugins_order_whichever_finds_them(plugin):
    directory = Directory(Path("repo"), is_repo=True)
    scan.check_all(directory, [plugin("b", finds=("b1", "b2")), plugin("a", finds=("a1",))])
    assert described(directory) == ["b1", "b2", "a1"]


def test_a_failed_fetch_follows_what_the_plugins_found(plugin):
    directory = Directory(Path("repo"), is_repo=True, fetch_failed=True)
    scan.check_all(directory, [plugin("a", finds=("a1",))])
    assert described(directory) == ["a1", "📡 fetch failed"]


def test_a_directory_of_files_is_checked_only_by_plugins_that_check_directories(plugin, calls):
    directory = Directory(Path("notes"), is_repo=False)
    scan.check_all(
        directory, [plugin("repos", finds=("r",)), plugin("all", checks_directories=True)]
    )
    assert calls == ["check all"]
    assert described(directory) == []


def test_when_git_cannot_read_a_repository_that_is_its_only_problem(plugin, calls):
    first = plugin("first", finds=("found",))
    broken = plugin("broken")
    broken.git_fails = True
    directory = Directory(Path("repo"), is_repo=True)
    scan.check_all(directory, [first, broken, plugin("last")])
    assert described(directory) == ["💥 git failed"]
    assert calls == ["check first", "check broken"]


def test_checking_again_starts_afresh(plugin):
    a = plugin("a", finds=("old",))
    broken = plugin("broken")
    broken.git_fails = True
    directory = Directory(Path("repo"), is_repo=True)
    scan.check_all(directory, [a, broken])
    a.finds = ("new",)
    broken.git_fails = False
    scan.check_all(directory, [a, broken])
    assert described(directory) == ["new"]


def test_every_directory_is_checked_by_every_plugin(projects, plugin):
    directories = [Directory(projects.local_repo(name), is_repo=True) for name in ("a", "b", "c")]
    found = [plugin("x", finds=("x",)), plugin("y", finds=("y",))]
    scan.survey(directories, found, fetch_first=False)
    assert [described(f) for f in directories] == [["x", "y"]] * 3


def test_worktrees_are_read_from_gits_porcelain_listing_the_main_one_first():
    porcelain = (
        "worktree /a\nHEAD 1111\nbranch refs/heads/main\n\n"
        "worktree /a-wt1\nHEAD 2222\ndetached\n\n"
        "worktree /gone\nHEAD 3333\nbranch refs/heads/feature\nprunable gitdir file points to "
        "non-existent location\n"
    )
    assert scan.parse_worktrees(porcelain) == [
        Worktree(Path("/a"), "main", prunable=False),
        Worktree(Path("/a-wt1"), None, prunable=False),
        Worktree(Path("/gone"), "feature", prunable=True),
    ]


def test_a_repositorys_worktrees_are_fetched_once_between_them(projects, plugin, monkeypatch):
    a = projects.pushed_repo("a")
    projects.worktree(a, "a-wt", "--detach")
    fetched = []
    monkeypatch.setattr(scan, "fetch", lambda repo: fetched.append(repo) or True)
    directories = scan.find(projects.root)
    scan.survey(directories, [], fetch_first=True)
    assert fetched == [a]
    assert [f.fetched for f in directories] == [True, True]
