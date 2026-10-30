"""repo-list and repo-fix ask for the integration of each repository that sets none."""

from pathlib import Path

from cli_kit.colour import BOLD, GREY, RESET, YELLOW

SETTINGS = Path(".config") / "ianf-repo-tools.toml"
SCHEMA = (
    "https://raw.githubusercontent.com/ianflanagan1/repo-tools/main/schema/ianf-repo-tools.v1.json"
)
NO_INTEGRATION = "✘ 🔧 Set `integration` in .config/ianf-repo-tools.toml"


def test_a_repository_with_no_integration_is_asked_for_one_by_its_path(projects, run, terminal):
    projects.integration(None)
    projects.pushed_repo("work/a")
    run()
    assert terminal.prompts == ["work/a: How and where does work reach the trunk?"]


def test_the_path_is_coloured_as_listed_and_the_question_apart(projects, run, terminal):
    projects.integration(None)
    projects.pushed_repo("work/a")
    terminal.colour = True
    run()
    question = "How and where does work reach the trunk?"
    assert terminal.prompts == [f"{GREY}work/{RESET}{BOLD}a{RESET}: {YELLOW}{question}{RESET}"]


def test_each_integration_is_offered_with_how_its_work_reaches_the_trunk_then_skip(
    projects, run, terminal
):
    projects.integration(None)
    projects.pushed_repo("a")
    run()
    assert terminal.options == [
        "direct     🏠 here, rebased onto trunk; only trunk pushed",
        "pr-rebase  📏 by pull request, rebased onto trunk",
        "pr-merge   🔀 by pull request, trunk merged in",
        "skip          leave it unset, and ask again next time",
    ]


def test_a_repository_with_an_integration_is_not_asked(projects, run, terminal):
    projects.pushed_repo("a")
    run()
    assert terminal.prompts == []


def test_a_repository_whose_integration_is_wrong_is_not_asked_as_its_file_needs_fixing_by_hand(
    projects, run, terminal
):
    a = projects.pushed_repo("a")
    (a / SETTINGS).write_text('version = 1\nintegration = "yolo"\n')
    run()
    assert terminal.prompts == []


def test_the_integration_chosen_is_written_in_a_new_settings_file_naming_its_schema(
    projects, run, terminal
):
    projects.integration(None)
    a = projects.pushed_repo("a")
    terminal.answer("pr-merge")
    run()
    assert (a / SETTINGS).read_text() == (
        f'#:schema {SCHEMA}\nversion = 1\nintegration = "pr-merge"\n'
    )


def test_the_integration_chosen_is_added_to_a_settings_file_keeping_what_is_there(
    projects, run, terminal
):
    projects.integration(None)
    a = projects.pushed_repo("a")
    (a / ".config").mkdir()
    (a / SETTINGS).write_text("# Ours.\nversion = 1\n")
    terminal.answer("direct")
    run()
    assert (a / SETTINGS).read_text() == '# Ours.\nversion = 1\nintegration = "direct"\n'


def test_the_repository_is_then_reported_in_the_integration_chosen(projects, run, terminal):
    projects.integration(None)
    projects.pushed_repo("a")
    terminal.answer("direct")
    assert run().listing == ["🏠 ❔    a  main  ✘ 📝 1 uncommitted file"]


def test_skipping_reports_the_integration_unset_and_asks_again_next_time(projects, run, terminal):
    projects.integration(None)
    a = projects.pushed_repo("a")
    terminal.answer("skip", "skip")
    assert run().listing == [f"🔧 ❔    a  main  {NO_INTEGRATION}"]
    run()
    assert len(terminal.prompts) == 2
    assert not (a / SETTINGS).exists()


def test_with_no_terminal_the_integration_is_reported_unset_and_nothing_written(projects, run):
    projects.integration(None)
    a = projects.pushed_repo("a")
    assert run().listing == [f"🔧 ❔    a  main  {NO_INTEGRATION}"]
    assert not (a / SETTINGS).exists()


def test_each_repository_with_no_integration_is_asked_in_turn(projects, run, terminal):
    projects.integration(None)
    a = projects.pushed_repo("a")
    b = projects.pushed_repo("b")
    terminal.answer("direct", "pr-rebase")
    run()
    assert len(terminal.prompts) == 2
    assert 'integration = "direct"' in (a / SETTINGS).read_text()
    assert 'integration = "pr-rebase"' in (b / SETTINGS).read_text()


def test_a_linked_worktree_with_no_integration_has_it_written_in_its_own_copy_only(
    projects, run, terminal
):
    projects.integration(None)
    a = projects.pushed_repo("a")
    linked = projects.worktree(a, "a-wt", "-b", "feature")
    terminal.answer("skip", "direct")
    run()
    assert terminal.prompts == [
        "a: How and where does work reach the trunk?",
        "a-wt: How and where does work reach the trunk?",
    ]
    assert 'integration = "direct"' in (linked / SETTINGS).read_text()
    assert not (a / SETTINGS).exists()
