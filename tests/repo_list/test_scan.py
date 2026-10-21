"""Behaviour of the scan's running of the plugins' checks, with the plugins faked."""

from pathlib import Path

from repo_list import scan
from repo_list.scan import Folder


def described(folder: Folder) -> list[str]:
    return [p.describe() for p in folder.problems]


def test_problems_are_in_the_plugins_order_whichever_finds_them(plugin):
    folder = Folder(Path("repo"), is_repo=True)
    scan.check_all(folder, [plugin("b", finds=("b1", "b2")), plugin("a", finds=("a1",))])
    assert described(folder) == ["b1", "b2", "a1"]


def test_a_failed_fetch_follows_what_the_plugins_found(plugin):
    folder = Folder(Path("repo"), is_repo=True, fetch_failed=True)
    scan.check_all(folder, [plugin("a", finds=("a1",))])
    assert described(folder) == ["a1", "📡 fetch failed"]


def test_a_folder_of_files_is_checked_only_by_plugins_that_check_folders(plugin, calls):
    folder = Folder(Path("notes"), is_repo=False)
    scan.check_all(folder, [plugin("repos", finds=("r",)), plugin("all", checks_folders=True)])
    assert calls == ["check all"]
    assert described(folder) == []


def test_when_git_cannot_read_a_repository_that_is_its_only_problem(plugin, calls):
    first = plugin("first", finds=("found",))
    broken = plugin("broken")
    broken.git_fails = True
    folder = Folder(Path("repo"), is_repo=True)
    scan.check_all(folder, [first, broken, plugin("last")])
    assert described(folder) == ["💥 git failed"]
    assert calls == ["check first", "check broken"]


def test_checking_again_starts_afresh(plugin):
    a = plugin("a", finds=("old",))
    broken = plugin("broken")
    broken.git_fails = True
    folder = Folder(Path("repo"), is_repo=True)
    scan.check_all(folder, [a, broken])
    a.finds = ("new",)
    broken.git_fails = False
    scan.check_all(folder, [a, broken])
    assert described(folder) == ["new"]


def test_every_folder_is_checked_by_every_plugin(projects, plugin):
    folders = [Folder(projects.local_repo(name), is_repo=True) for name in ("a", "b", "c")]
    scan.survey(folders, [plugin("x", finds=("x",)), plugin("y", finds=("y",))], fetch_first=False)
    assert [described(f) for f in folders] == [["x", "y"]] * 3
