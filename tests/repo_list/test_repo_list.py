"""Behaviour of repo_list.py."""

import os

import pytest
from cli_kit.errors import Failure

from repo_tools.packagist import api as packagist_api

# --- A repository's state


def test_a_repository_with_everything_committed_and_pushed_is_clean(projects, run):
    projects.pushed_repo("a")
    assert run().listing == ["✔ a"]


def test_uncommitted_files_are_reported_whether_changed_or_untracked(projects, run):
    a = projects.pushed_repo("a")
    (a / "f").write_text("change\n")
    (a / "g").write_text("new\n")
    assert run().listing == ["✘ a  📝 2 uncommitted files"]


def test_counts_of_one_are_singular(projects, run):
    a = projects.pushed_repo("a")
    (a / "g").write_text("new\n")
    assert run().listing == ["✘ a  📝 1 uncommitted file"]


def test_commits_on_no_remote_are_reported_for_each_branch(projects, run):
    a = projects.pushed_repo("a")
    projects.commit(a, "one")
    projects.git("-C", a, "checkout", "-qb", "feature")
    projects.commit(a, "two")
    assert run().listing == ["✘ a  📤 2 unpushed on feature  📤 1 unpushed on main"]


def test_a_branch_without_an_upstream_is_clean_when_its_commits_are_on_a_remote(projects, run):
    a = projects.pushed_repo("a")
    projects.git("-C", a, "branch", "copy")
    assert run().listing == ["✔ a"]


def test_a_repository_without_a_remote_is_reported_once_rather_than_every_commit_as_unpushed(
    projects, run
):
    a = projects.local_repo("a")
    projects.commit(a, "one")
    assert run().listing == ["✘ a  🔌 no remote"]


def test_commits_only_on_a_detached_head_are_reported(projects, run):
    a = projects.pushed_repo("a")
    projects.git("-C", a, "checkout", "-q", "--detach")
    projects.commit(a, "lost")
    assert run().listing == ["✘ a  👻 1 commit on detached HEAD"]


def test_stashes_are_reported(projects, run):
    a = projects.pushed_repo("a")
    (a / "f").write_text("change\n")
    projects.git("-C", a, "stash", "-q")
    assert run().listing == ["✘ a  📦 1 stash"]


def test_a_branch_behind_its_upstream_by_the_last_fetch_is_reported(projects, run):
    a = projects.pushed_repo("a")
    projects.push_from_elsewhere(a)
    assert run().listing == ["✔ a"], "without a fetch, nothing is known"
    projects.git("-C", a, "fetch", "-q")
    assert run().listing == ["✘ a  📥 1 behind on main"]


def test_fetching_first_finds_a_branch_behind_its_upstream(projects, run):
    a = projects.pushed_repo("a")
    projects.push_from_elsewhere(a)
    assert run("--fetch").listing == ["✘ a  📥 1 behind on main"]


def test_a_failed_fetch_is_reported(projects, run):
    a = projects.pushed_repo("a")
    projects.git("-C", a, "remote", "set-url", "origin", projects.remotes / "missing.git")
    assert run("-f").listing == ["✘ a  📡 fetch failed"]


def test_a_broken_repository_is_reported(projects, run):
    (projects.root / "a").mkdir()
    (projects.root / "a" / ".git").write_text("not a repository\n")
    assert run().listing == ["✘ a  💥 git failed"]


def test_problems_line_up_after_the_longest_path(projects, run):
    projects.local_repo("a")
    projects.pushed_repo("bbb")
    projects.local_repo("cc")
    assert run().listing == ["✘ a    🔌 no remote", "✔ bbb", "✘ cc   🔌 no remote"]


# --- Finding repositories


def test_repositories_are_listed_by_path_from_the_root_in_name_order(projects, run):
    projects.pushed_repo("b")
    projects.pushed_repo("a")
    (projects.root / "group").mkdir()
    projects.pushed_repo("group/c")
    assert run().listing == ["✔ a", "✔ b", "✔ group/c"]


def test_a_folder_of_files_in_no_repository_is_reported(projects, run):
    (projects.root / "notes").mkdir()
    (projects.root / "notes" / "todo").write_text("x\n")
    assert run().listing == ["✘ notes  📁 not a git repository"]


def test_a_folder_holding_only_folders_is_searched_rather_than_reported(projects, run):
    (projects.root / "group" / "sub").mkdir(parents=True)
    (projects.root / "group" / ".DS_Store").write_text("x\n")
    projects.pushed_repo("group/sub/a")
    assert run().listing == ["✔ group/sub/a"]


def test_empty_folders_are_skipped(projects, run):
    (projects.root / "empty" / "inner").mkdir(parents=True)
    projects.pushed_repo("a")
    assert run().listing == ["✔ a"]


def test_repositories_inside_a_repository_are_not_searched_for(projects, run):
    a = projects.pushed_repo("a")
    projects.git("init", "-q", a / "inner")
    with open(a / ".git" / "info" / "exclude", "a") as exclude:
        exclude.write("inner\n")
    assert run().listing == ["✔ a"]


def test_hidden_folders_and_symlinks_are_skipped(projects, run):
    (projects.root / ".hidden").mkdir()
    (projects.root / ".hidden" / "f").write_text("x\n")
    projects.pushed_repo("a")
    os.symlink(projects.root / "a", projects.root / "link")
    assert run().listing == ["✔ a"]


def test_a_root_without_repositories_says_so(projects, run):
    assert run().listing == [f"No repositories under {projects.root.resolve()}"]


# --- Packagist


def test_with_the_packagist_flag_a_package_packagist_is_up_to_date_on_is_clean(
    projects, packagist, run
):
    projects.package("a")
    packagist.has("me/a")
    assert run("-p").listing == ["✔ a"]


def test_with_the_packagist_flag_a_package_not_on_packagist_is_reported(projects, run):
    projects.package("a")
    assert run("-p").listing == ["✘ a  🐘 not on Packagist"]


def test_with_the_packagist_flag_what_packagist_lacks_of_a_package_is_reported(
    projects, packagist, run
):
    projects.package("a")
    packagist.has("me/a", lacking=["main", "v0.2.0"])
    assert run("-p").listing == ["✘ a  🐘 Packagist lacks main, v0.2.0"]


def test_a_package_packagist_could_not_be_checked_for_is_reported(projects, run, monkeypatch):
    def unreachable(package, directory):
        raise Failure("Couldn't reach Packagist.")

    projects.package("a")
    monkeypatch.setattr(packagist_api, "lacks", unreachable)
    assert run("-p").listing == ["✘ a  🐘 Packagist check failed"]


def test_without_the_packagist_flag_packagist_is_not_checked(projects, run):
    projects.package("a")
    assert run("-f").listing == ["✔ a"]


def test_a_package_of_another_vendor_is_not_checked(projects, run):
    projects.package("a", vendor="someone")
    assert run("-p").listing == ["✔ a"]


def test_a_package_whose_fetch_failed_is_not_checked(projects, run):
    a = projects.package("a")
    projects.git("-C", a, "remote", "set-url", "origin", projects.remotes / "missing.git")
    assert run("-f", "-p").listing == ["✘ a  📡 fetch failed"]


def test_the_packagist_flag_without_a_vendor_in_the_config_is_a_usage_error(projects, run):
    projects.config.write_text('root = "~/projects"\n')
    with pytest.raises(SystemExit) as exit:
        run("-p")
    assert exit.value.code == 2


# --- The root


def test_the_root_is_projects_in_the_home_folder_wherever_it_is_run_from(
    projects, run, monkeypatch
):
    (projects.root / "group").mkdir()
    a = projects.pushed_repo("group/a")
    projects.pushed_repo("b")
    monkeypatch.chdir(a)
    assert run().listing == ["✔ b", "✔ group/a"]


def test_a_root_given_is_searched_instead(projects, run, monkeypatch):
    (projects.root / "group").mkdir()
    projects.pushed_repo("group/a")
    projects.pushed_repo("b")
    monkeypatch.chdir("/")
    assert run(projects.root / "group").listing == ["✔ a"]


def test_the_root_in_the_config_is_the_default_instead(projects, run):
    (projects.root / "group").mkdir()
    projects.pushed_repo("group/a")
    projects.pushed_repo("b")
    projects.config.write_text(f'root = "{projects.root / "group"}"\n')
    assert run().listing == ["✔ a"]


def test_a_config_that_cannot_be_read_is_a_usage_error(projects, run):
    projects.config.write_text("root = \n")
    with pytest.raises(SystemExit) as exit:
        run()
    assert exit.value.code == 2


def test_a_root_that_is_not_a_directory_is_a_usage_error(run):
    with pytest.raises(SystemExit) as exit:
        run("missing")
    assert exit.value.code == 2


# --- Colour


def test_on_a_terminal_the_parent_path_name_and_problems_are_coloured_apart(
    projects, run, monkeypatch
):
    monkeypatch.setenv("FORCE_COLOR", "1")
    (projects.root / "group").mkdir()
    projects.local_repo("group/a")
    assert run().listing == [
        "\x1b[31m✘\x1b[0m \x1b[38;5;246mgroup/\x1b[0m\x1b[1ma\x1b[0m  \x1b[33m🔌 no remote\x1b[0m"
    ]


def test_no_color_turns_colour_off_even_when_forced(projects, run, monkeypatch):
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.setenv("NO_COLOR", "1")
    projects.local_repo("a")
    assert run().listing == ["✘ a  🔌 no remote"]


# --- The summary


def test_the_summary_counts_the_repositories_needing_attention(projects, run):
    projects.pushed_repo("a")
    projects.local_repo("b")
    c = projects.pushed_repo("c")
    (c / "f").write_text("change\n")
    assert run().summary == "✘ 2 of 3 need attention"


def test_the_summary_says_when_all_are_clean(projects, run):
    projects.pushed_repo("a")
    projects.pushed_repo("b")
    assert run().summary == "✔ All 2 clean"


def test_the_exit_status_is_0_when_all_are_clean_and_1_otherwise(projects, run):
    projects.pushed_repo("a")
    assert run().status == 0
    projects.local_repo("b")
    assert run().status == 1
