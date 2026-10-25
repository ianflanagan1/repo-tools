"""Behaviour of repo_list.py."""

import os

import pytest
from cli_kit.outcome import Failure

import repo_list
from repo_tools.npmjs import api as npm_api
from repo_tools.packagist import api as packagist_api

# --- A repository's state


def test_a_repository_with_everything_committed_and_pushed_is_clean(projects, run):
    projects.pushed_repo("a")
    assert run("-a").listing == ["🏠 ❔    a  main  ✔"]


def test_uncommitted_files_are_reported_whether_changed_or_untracked(projects, run):
    a = projects.pushed_repo("a")
    (a / "f").write_text("change\n")
    (a / "g").write_text("new\n")
    assert run().listing == ["🏠 ❔    a  main  ✘ 📝 2 uncommitted files"]


def test_counts_of_one_are_singular(projects, run):
    a = projects.pushed_repo("a")
    (a / "g").write_text("new\n")
    assert run().listing == ["🏠 ❔    a  main  ✘ 📝 1 uncommitted file"]


def test_with_local_integration_the_trunk_reports_commits_to_push_and_other_branches_work_to_land(
    projects, run
):
    a = projects.pushed_repo("a")
    projects.commit(a, "one")
    projects.git("-C", a, "checkout", "-qb", "feature")
    projects.commit(a, "two")
    projects.git("-C", a, "checkout", "-q", "main")
    assert run().listing == ["🏠 ❔    a  main  ✘ 📤 1 unpushed on main  🛬 1 unmerged on feature"]


def test_with_pr_integration_commits_on_the_trunk_belong_on_a_branch_and_other_branches_are_pushed(
    projects, run
):
    projects.integration("pr-merge")
    a = projects.pushed_repo("a")
    projects.commit(a, "one")
    projects.git("-C", a, "checkout", "-qb", "feature")
    projects.commit(a, "two")
    projects.git("-C", a, "checkout", "-q", "main")
    assert run().listing == ["🔀 ❔    a  main  ✘ ⛔ 1 commit on main  📤 2 unpushed on feature"]


def test_a_repositorys_settings_file_sets_its_own_integration(projects, run):
    a = projects.pushed_repo("a")
    (a / ".config" / "ianf-repo-tools.toml").write_text('version = 1\nintegration = "pr-rebase"\n')
    projects.git("-C", a, "add", "-A")
    projects.git("-C", a, "commit", "-qm", "settings")
    assert run().listing == ["📏 ❔    a  main  ✘ ⛔ 1 commit on main"]


def test_a_repository_with_no_integration_set_anywhere_reports_that_alone(projects, run):
    projects.integration(None)
    a = projects.pushed_repo("a")
    projects.commit(a, "local")
    assert run().listing == [
        "🔧 ❔    a  main  ✘ 🔧 Set `integration` in .config/ianf-repo-tools.toml"
    ]


def test_an_integration_the_settings_file_names_wrongly_is_reported(projects, run):
    a = projects.pushed_repo("a")
    (a / ".config" / "ianf-repo-tools.toml").write_text('version = 1\nintegration = "yolo"\n')
    assert run().listing == [
        "🔧 ❔    a  main  ✘ 🔧 .config/ianf-repo-tools.toml: integration must be one of local, "
        "pr-rebase, pr-merge"
    ]


def test_a_repository_whose_settings_file_sets_skip_fix_is_marked(projects, run):
    a = projects.pushed_repo("a")
    (a / ".config" / "ianf-repo-tools.toml").write_text(
        'version = 1\nintegration = "local"\nskip-fix = true\n'
    )
    assert run("-a").listing == ["🏠 ❔    a  main  💤 repo-fix skips  ✘ 📝 1 uncommitted file"]


def test_a_skip_fix_that_is_not_true_or_false_is_reported(projects, run):
    a = projects.pushed_repo("a")
    (a / ".config" / "ianf-repo-tools.toml").write_text(
        'version = 1\nintegration = "local"\nskip-fix = "yes"\n'
    )
    assert run().listing == [
        "🏠 ❔    a  main  ✘ 🔧 .config/ianf-repo-tools.toml: skip-fix must be true or false"
    ]


def test_a_settings_file_without_a_version_is_reported(projects, run):
    a = projects.pushed_repo("a")
    (a / ".config" / "ianf-repo-tools.toml").write_text('integration = "local"\n')
    listing = run().listing
    assert listing[0].startswith(
        "🔧 ❔    a  main  ✘ 🔧 No version in .config/ianf-repo-tools.toml. Add version = 1"
    )


def test_a_branch_without_an_upstream_is_clean_when_its_commits_are_on_a_remote(projects, run):
    a = projects.pushed_repo("a")
    projects.git("-C", a, "branch", "copy")
    assert run("-a").listing == ["🏠 ❔    a  main  ✔"]


def test_a_repository_without_a_remote_is_reported_once_rather_than_every_commit_as_unpushed(
    projects, run
):
    a = projects.local_repo("a")
    projects.commit(a, "one")
    assert run().listing == ["🏠 🔌    a  main  ✘ 🔌 no remote"]


def test_commits_only_on_a_detached_head_are_reported(projects, run):
    a = projects.pushed_repo("a")
    projects.git("-C", a, "checkout", "-q", "--detach")
    projects.commit(a, "lost")
    head = projects.short_head(a)
    assert run().listing == [f"🏠 ❔    a  @{head}  ✘ 👻 1 commit on detached HEAD"]


def test_the_branch_checked_out_is_shown_without_needing_attention(projects, run):
    a = projects.pushed_repo("a")
    projects.git("-C", a, "checkout", "-qb", "spike")
    assert run("-a").listing == ["🏠 ❔    a  spike  ✔"]


def test_a_worktree_shows_its_own_branch(projects, run):
    a = projects.pushed_repo("a")
    projects.worktree(a, "a-wt", "-b", "feature")
    assert run("-a").listing == ["🏠 ❔    a     main     ✔", "🏠 ❔    a-wt  feature  ✔"]


# --- Worktrees


def test_a_linked_worktree_does_not_report_the_trunk_its_main_worktree_reports(projects, run):
    a = projects.pushed_repo("a")
    projects.commit(a, "local")
    wt = projects.worktree(a, "a-wt", "--detach")
    assert run("-a").listing == [
        "🏠 ❔    a     main      ✘ 📤 1 unpushed on main",
        f"🏠 ❔    a-wt  @{projects.short_head(wt)}  ✔",
    ]


def test_a_branch_checked_out_in_a_linked_worktree_is_reported_there_alone(projects, run):
    a = projects.pushed_repo("a")
    wt = projects.worktree(a, "a-wt", "-b", "feature")
    projects.commit(wt, "feature work")
    assert run("-a").listing == [
        "🏠 ❔    a     main     ✔",
        "🏠 ❔    a-wt  feature  ✘ 🛬 1 unmerged on feature",
    ]


def test_the_main_worktree_reports_branches_no_worktree_has_checked_out(projects, run):
    a = projects.pushed_repo("a")
    wt = projects.worktree(a, "a-wt", "-b", "feature")
    projects.commit(wt, "feature work")
    projects.git("-C", wt, "checkout", "-q", "--detach")
    assert run().listing == ["🏠 ❔    a  main  ✘ 🛬 1 unmerged on feature"]


def test_a_worktree_behind_the_trunk_says_how_far(projects, run):
    a = projects.pushed_repo("a")
    wt = projects.worktree(a, "a-wt", "--detach")
    projects.commit(a, "more")
    projects.git("-C", a, "push", "-q")
    assert run().listing == [f"🏠 ❔    a-wt  @{projects.short_head(wt)}  ✘ 🔄 1 behind main"]


def test_a_worktree_whose_catching_up_would_conflict_says_so(projects, run):
    a = projects.pushed_repo("a")
    wt = projects.worktree(a, "a-wt", "-b", "feature")
    projects.commit(wt, "feature work")
    projects.commit(a, "more")
    projects.git("-C", a, "push", "-q")
    assert run().listing == [
        "🏠 ❔    a-wt  feature  ✘ 🛬 1 unmerged on feature  ⚡ conflicts with main"
    ]


def test_with_pr_integration_a_branch_is_measured_against_the_trunk_on_the_remote(projects, run):
    projects.integration("pr-rebase")
    a = projects.pushed_repo("a")
    projects.worktree(a, "a-wt", "-b", "feature")
    projects.push_from_elsewhere(a)
    assert run("--fetch").listing == [
        "📏 ❔    a     main     ✘ 📥 1 behind on main",
        "📏 ❔    a-wt  feature  ✘ 🔄 1 behind origin/main",
    ]


def test_a_directory_a_claude_code_session_is_busy_in_is_marked(projects, run):
    a = projects.pushed_repo("a")
    projects.claude_session(a, "s1", "busy")
    assert run("-a").listing == ["🏠 ❔    a  main  🤖 Claude working  ✔"]


def test_an_idle_claude_code_session_is_not_marked(projects, run):
    a = projects.pushed_repo("a")
    projects.claude_session(a, "s1", "idle")
    assert run("-a").listing == ["🏠 ❔    a  main  ✔"]


def test_a_detached_worktree_with_no_commits_of_its_own_is_clean(projects, run):
    a = projects.pushed_repo("a")
    projects.git("-C", a, "worktree", "add", "-q", "--detach", projects.root / "a-wt")
    assert run("-a").listing == [
        "🏠 ❔    a     main      ✔",
        f"🏠 ❔    a-wt  @{projects.short_head(a)}  ✔",
    ]


def test_stashes_are_reported(projects, run):
    a = projects.pushed_repo("a")
    (a / "f").write_text("change\n")
    projects.git("-C", a, "stash", "-q")
    assert run().listing == ["🏠 ❔    a  main  ✘ 📦 1 stash"]


def test_a_branch_behind_its_upstream_by_the_last_fetch_is_reported(projects, run):
    a = projects.pushed_repo("a")
    projects.push_from_elsewhere(a)
    assert run("-a").listing == ["🏠 ❔    a  main  ✔"], "without a fetch, nothing is known"
    projects.git("-C", a, "fetch", "-q")
    assert run().listing == ["🏠 ❔    a  main  ✘ 📥 1 behind on main"]


def test_fetching_first_finds_a_branch_behind_its_upstream(projects, run):
    a = projects.pushed_repo("a")
    projects.push_from_elsewhere(a)
    assert run("--fetch").listing == ["🏠 ❔    a  main  ✘ 📥 1 behind on main"]


def test_a_failed_fetch_is_reported(projects, run):
    a = projects.pushed_repo("a")
    projects.git("-C", a, "remote", "set-url", "origin", projects.remotes / "missing.git")
    assert run("-f").listing == ["🏠 ❔    a  main  ✘ 📡 fetch failed"]


def test_a_broken_repository_is_reported(projects, run):
    (projects.root / "a").mkdir()
    (projects.root / "a" / ".git").write_text("not a repository\n")
    assert run().listing == ["a  ✘ 💥 git failed"]


def test_problems_line_up_after_the_longest_path(projects, run):
    projects.local_repo("a")
    projects.pushed_repo("bbb")
    projects.local_repo("cc")
    assert run("-a").listing == [
        "🏠 🔌    a    main  ✘ 🔌 no remote",
        "🏠 ❔    bbb  main  ✔",
        "🏠 🔌    cc   main  ✘ 🔌 no remote",
    ]


def test_problems_line_up_after_the_branches_even_for_a_directory_without_one(projects, run):
    projects.local_repo("a")
    (projects.root / "notes").mkdir()
    (projects.root / "notes" / "todo").write_text("x\n")
    assert run().listing == [
        "🏠 🔌    a      main  ✘ 🔌 no remote",
        "         notes        ✘ 📁 not a git repository",
    ]


# --- Finding repositories


def test_repositories_are_listed_by_path_from_the_root_in_name_order(projects, run):
    projects.pushed_repo("b")
    projects.pushed_repo("a")
    (projects.root / "group").mkdir()
    projects.pushed_repo("group/c")
    assert run("-a").listing == [
        "🏠 ❔    a        main  ✔",
        "🏠 ❔    b        main  ✔",
        "🏠 ❔    group/c  main  ✔",
    ]


def test_a_directory_of_files_in_no_repository_is_reported(projects, run):
    (projects.root / "notes").mkdir()
    (projects.root / "notes" / "todo").write_text("x\n")
    assert run().listing == ["notes  ✘ 📁 not a git repository"]


def test_a_directory_holding_only_directories_is_searched_rather_than_reported(projects, run):
    (projects.root / "group" / "sub").mkdir(parents=True)
    (projects.root / "group" / ".DS_Store").write_text("x\n")
    projects.pushed_repo("group/sub/a")
    assert run("-a").listing == ["🏠 ❔    group/sub/a  main  ✔"]


def test_empty_directories_are_skipped(projects, run):
    (projects.root / "empty" / "inner").mkdir(parents=True)
    projects.pushed_repo("a")
    assert run("-a").listing == ["🏠 ❔    a  main  ✔"]


def test_repositories_inside_a_repository_are_not_searched_for(projects, run):
    a = projects.pushed_repo("a")
    projects.git("init", "-q", a / "inner")
    with open(a / ".git" / "info" / "exclude", "a") as exclude:
        exclude.write("inner\n")
    assert run("-a").listing == ["🏠 ❔    a  main  ✔"]


def test_hidden_directories_and_symlinks_are_skipped(projects, run):
    (projects.root / ".hidden").mkdir()
    (projects.root / ".hidden" / "f").write_text("x\n")
    projects.pushed_repo("a")
    os.symlink(projects.root / "a", projects.root / "link")
    assert run("-a").listing == ["🏠 ❔    a  main  ✔"]


def test_a_root_without_repositories_says_so(projects, run):
    assert run().summary == f"No repositories under {projects.root.resolve()}"


# --- Packagist


def test_with_the_packagist_flag_a_package_packagist_is_up_to_date_on_is_clean(
    projects, packagist, run
):
    projects.package("a")
    packagist.has("me/a")
    assert run("-a", "-p").listing == ["🏠 ❔    🐘 a  main  ✔"]


def test_with_the_packagist_flag_a_package_not_on_packagist_is_reported(projects, run):
    projects.package("a")
    assert run("-p").listing == ["🏠 ❔    🐘 a  main  ✘ 🐘 not on Packagist"]


def test_with_the_packagist_flag_what_packagist_lacks_of_a_package_is_reported(
    projects, packagist, run
):
    projects.package("a")
    packagist.has("me/a", lacking=["main", "v0.2.0"])
    assert run("-p").listing == ["🏠 ❔    🐘 a  main  ✘ 🐘 Packagist lacks main, v0.2.0"]


def test_a_package_packagist_could_not_be_checked_for_is_reported(projects, run, monkeypatch):
    def unreachable(package, directory):
        raise Failure("Couldn't reach Packagist.")

    projects.package("a")
    monkeypatch.setattr(packagist_api, "lacks", unreachable)
    assert run("-p").listing == ["🏠 ❔    🐘 a  main  ✘ 🐘 Packagist check failed"]


def test_without_the_packagist_flag_packagist_is_not_checked(projects, run):
    projects.package("a")
    assert run("-a", "-f").listing == ["🏠 ❔    🐘 a  main  ✔"]


def test_a_package_of_another_vendor_is_not_checked(projects, run):
    projects.package("a", vendor="someone")
    assert run("-a", "-p").listing == ["🏠 ❔    🐘 a  main  ✔"]


def test_a_composer_project_of_the_vendor_is_an_app_and_is_not_checked(projects, run):
    a = projects.pushed_repo("a")
    (a / "composer.json").write_text('{"name": "me/a", "type": "project"}')
    projects.git("-C", a, "add", "-A")
    projects.git("-C", a, "commit", "-qm", "composer.json")
    projects.git("-C", a, "push", "-q")
    assert run("-a", "-p").listing == ["🏠 ❔    a  main  ✔"]


def test_a_package_whose_fetch_failed_is_not_checked(projects, run):
    a = projects.package("a")
    projects.git("-C", a, "remote", "set-url", "origin", projects.remotes / "missing.git")
    assert run("-f", "-p").listing == ["🏠 ❔    🐘 a  main  ✘ 📡 fetch failed"]


def test_the_packagist_flag_without_a_vendor_in_the_config_is_a_usage_error(projects, run):
    projects.config.write_text('root = "~/projects"\n')
    with pytest.raises(SystemExit) as exit:
        run("-p")
    assert exit.value.code == 2


# --- npm


def test_with_the_npm_flag_a_package_npm_is_up_to_date_on_is_clean(projects, npm, run):
    projects.npm_package("a", {"name": "@me/a"})
    npm.has("@me/a", lacking=[])
    assert run("-a", "--npm").listing == ["🏠 ❔    🔴 a  main  ✔"]


def test_with_the_npm_flag_a_package_not_on_npm_is_reported(projects, run):
    projects.npm_package("a", {"name": "@me/a"})
    assert run("--npm").listing == ["🏠 ❔    🔴 a  main  ✘ 🔴 not on npm"]


def test_with_the_npm_flag_the_version_tags_npm_lacks_are_reported(projects, npm, run):
    projects.npm_package("a", {"name": "@me/a"})
    npm.has("@me/a", lacking=["v0.2.0", "v0.3.0"])
    assert run("--npm").listing == ["🏠 ❔    🔴 a  main  ✘ 🔴 npm lacks v0.2.0, v0.3.0"]


def test_a_package_npm_could_not_be_checked_for_is_reported(projects, run, monkeypatch):
    def unreachable(package, directory):
        raise Failure("Couldn't reach npm.")

    projects.npm_package("a", {"name": "@me/a"})
    monkeypatch.setattr(npm_api, "lacks", unreachable)
    assert run("--npm").listing == ["🏠 ❔    🔴 a  main  ✘ 🔴 npm check failed"]


def test_a_private_package_is_not_checked(projects, run):
    projects.npm_package("a", {"name": "@me/a", "private": True})
    assert run("-a", "--npm").listing == ["🏠 ❔    a  main  ✔"]


def test_a_package_outside_the_scope_is_not_checked(projects, run):
    projects.npm_package("a", {"name": "@someone/a"})
    projects.npm_package("b", {"name": "b"})
    assert run("-a", "--npm").listing == ["🏠 ❔    🔴 a  main  ✔", "🏠 ❔    🔴 b  main  ✔"]


def test_without_the_npm_flag_npm_is_not_checked(projects, run):
    projects.npm_package("a", {"name": "@me/a"})
    assert run("-a").listing == ["🏠 ❔    🔴 a  main  ✔"]


def test_the_npm_flag_without_a_scope_in_the_config_is_a_usage_error(projects, run):
    projects.config.write_text('root = "~/projects"\n')
    with pytest.raises(SystemExit) as exit:
        run("--npm")
    assert exit.value.code == 2


# --- The root


def test_the_root_is_projects_in_the_home_directory_wherever_it_is_run_from(
    projects, run, monkeypatch
):
    (projects.root / "group").mkdir()
    a = projects.pushed_repo("group/a")
    projects.pushed_repo("b")
    monkeypatch.chdir(a)
    assert run("-a").listing == ["🏠 ❔    b        main  ✔", "🏠 ❔    group/a  main  ✔"]


def test_a_root_given_is_searched_instead(projects, run, monkeypatch):
    (projects.root / "group").mkdir()
    projects.pushed_repo("group/a")
    projects.pushed_repo("b")
    monkeypatch.chdir("/")
    assert run("-a", projects.root / "group").listing == ["🏠 ❔    a  main  ✔"]


def test_the_root_in_the_config_is_the_default_instead(projects, run):
    (projects.root / "group").mkdir()
    projects.pushed_repo("group/a")
    projects.pushed_repo("b")
    projects.config.write_text(f'root = "{projects.root / "group"}"\n')
    assert run("-a").listing == ["🏠 ❔    a  main  ✔"]


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
        "🏠 🔌    \x1b[38;5;246mgroup/\x1b[0m\x1b[1ma\x1b[0m  "
        "\x1b[38;5;246mmain\x1b[0m  \x1b[31m✘\x1b[0m \x1b[33m🔌 no remote\x1b[0m"
    ]


def test_on_a_terminal_the_trunk_is_grey_and_any_other_stands_out(projects, run, monkeypatch):
    monkeypatch.setenv("FORCE_COLOR", "1")
    a = projects.pushed_repo("a")
    projects.git("-C", a, "worktree", "add", "-qb", "feature", projects.root / "b")
    assert run("-a").listing == [
        "🏠 ❔    \x1b[1ma\x1b[0m  \x1b[38;5;246mmain\x1b[0m     \x1b[32m✔\x1b[0m",
        "🏠 ❔    \x1b[1mb\x1b[0m  feature  \x1b[32m✔\x1b[0m",
    ]


def test_no_color_turns_colour_off_even_when_forced(projects, run, monkeypatch):
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.setenv("NO_COLOR", "1")
    projects.local_repo("a")
    assert run().listing == ["🏠 🔌    a  main  ✘ 🔌 no remote"]


# --- Clean repositories


def test_clean_repositories_are_left_out_of_the_listing(projects, run):
    projects.pushed_repo("a")
    projects.local_repo("b")
    assert run().listing == ["🏠 🔌    b  main  ✘ 🔌 no remote"]


def test_the_all_flag_lists_clean_repositories_too(projects, run):
    projects.pushed_repo("a")
    projects.local_repo("b")
    assert run("--all").listing == ["🏠 ❔    a  main  ✔", "🏠 🔌    b  main  ✘ 🔌 no remote"]
    assert run("-a").listing == ["🏠 ❔    a  main  ✔", "🏠 🔌    b  main  ✘ 🔌 no remote"]


def test_columns_line_up_with_only_the_repositories_listed(projects, run):
    a = projects.pushed_repo("a")
    projects.git("-C", a, "checkout", "-qb", "a-long-branch")
    projects.pushed_repo("a-long-name")
    projects.local_repo("b")
    assert run().listing == ["🏠 🔌    b  main  ✘ 🔌 no remote"]


def test_when_all_are_clean_only_the_summary_is_shown(projects, capsys):
    projects.pushed_repo("a")
    projects.pushed_repo("b")
    assert repo_list.main([]) == 0
    assert capsys.readouterr().out == "✔ All 2 clean\n"


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
