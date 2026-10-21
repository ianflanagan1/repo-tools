"""Behaviour of repo-fix's running of the plugins' fixes, with the plugins faked."""

from pathlib import Path

from repo_list import fix, scan
from repo_list.plugin import Stage
from repo_list.scan import Folder


def surveyed(*plugins) -> Folder:
    folder = Folder(Path("repo"), is_repo=True)
    scan.check_all(folder, list(plugins))
    return folder


def run(folder: Folder, *plugins) -> list[tuple[bool, str]]:
    """Runs the fixes, returning what they logged."""
    logged: list[tuple[bool, str]] = []
    fix.fix(folder, list(plugins), lambda ok, line, *details: logged.append((ok, line)))
    return logged


def fixes(calls: list[str]) -> list[str]:
    return [call for call in calls if call.startswith("fix")]


def test_fixes_run_stage_by_stage_whatever_order_the_plugins_are_in(plugin, calls):
    plugins = [
        plugin("tell", stage=Stage.AFTER_PUSH, finds=("t",)),
        plugin("push", stage=Stage.SYNC, finds=("p",)),
        plugin("commit", stage=Stage.COMMIT, finds=("c",)),
    ]
    run(surveyed(*plugins), *plugins)
    assert fixes(calls) == ["fix commit: c", "fix push: p", "fix tell: t"]


def test_a_plugin_is_given_what_its_own_check_found(plugin, calls):
    a = plugin("a", stage=Stage.COMMIT, finds=("one", "two"))
    b = plugin("b", stage=Stage.COMMIT, finds=("three",))
    run(surveyed(a, b), a, b)
    assert fixes(calls) == ["fix a: one, two", "fix b: three"]


def test_a_plugin_that_found_nothing_is_not_fixed(plugin, calls):
    a = plugin("a", stage=Stage.COMMIT)
    run(surveyed(a), a)
    assert fixes(calls) == []


def test_a_plugin_without_a_stage_only_checks(plugin, calls):
    a = plugin("a", finds=("x",))
    run(surveyed(a), a)
    assert fixes(calls) == []


def test_a_failed_fix_stops_the_folder_there(plugin, calls):
    commit = plugin("commit", stage=Stage.COMMIT, finds=("c",))
    push = plugin("push", stage=Stage.SYNC, finds=("p",))
    commit.fails = True
    run(surveyed(commit, push), commit, push)
    assert fixes(calls) == ["fix commit: c"]


def test_once_a_fix_has_run_each_later_plugin_checks_again_before_its_fix(plugin, calls):
    commit = plugin("commit", stage=Stage.COMMIT, finds=("work",))
    push = plugin("push", stage=Stage.SYNC)
    folder = surveyed(commit, push)
    commit.then = lambda: setattr(push, "finds", ("new commits",))
    calls.clear()
    run(folder, commit, push)
    assert calls == ["fix commit: work", "check push", "fix push: new commits"]


def test_until_a_fix_has_run_nothing_is_checked_again(plugin, calls):
    commit = plugin("commit", stage=Stage.COMMIT)
    tell = plugin("tell", stage=Stage.AFTER_PUSH, finds=("t",))
    folder = surveyed(commit, tell)
    calls.clear()
    run(folder, commit, tell)
    assert calls == ["fix tell: t"]


def test_a_folder_git_could_not_read_is_not_fixed(plugin, calls):
    a = plugin("a", stage=Stage.COMMIT, finds=("x",))
    b = plugin("b", stage=Stage.SYNC)
    b.git_fails = True
    run(surveyed(a, b), a, b)
    assert fixes(calls) == []


def test_git_failing_to_read_the_folder_after_a_fix_stops_the_folder_there(plugin, calls):
    commit = plugin("commit", stage=Stage.COMMIT, finds=("c",))
    push = plugin("push", stage=Stage.SYNC, finds=("p",))
    tell = plugin("tell", stage=Stage.AFTER_PUSH, finds=("t",))
    folder = surveyed(commit, push, tell)
    push.git_fails = True
    run(folder, commit, push, tell)
    assert fixes(calls) == ["fix commit: c"]
    assert [p.describe() for p in folder.problems] == ["💥 git failed"]
