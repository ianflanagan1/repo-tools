"""repo-list reports origin when it isn't on the git host a repository's
.config/ianf-repo-tools.toml puts it on."""

from pathlib import Path

SETTINGS = Path(".config") / "ianf-repo-tools.toml"
ELSEWHERE = "though .config/ianf-repo-tools.toml puts it on GitHub"


def put_origin_on(projects, repo: Path, table: str) -> None:
    """Commits and pushes settings whose remotes are table, as TOML after [remotes]."""
    (repo / SETTINGS).write_text(f'version = 1\nintegration = "direct"\n\n{table}')
    projects.git("-C", repo, "commit", "--quiet", "--all", "--message", "Settings")
    projects.git("-C", repo, "push", "--quiet")


def on_github(projects, repo: Path) -> None:
    put_origin_on(projects, repo, '[remotes.origin]\ngit-host = "github"\n')


def test_origin_on_the_git_host_the_settings_name_is_clean(projects, run):
    a = projects.pushed_repo("a")
    put_origin_on(projects, a, '[remotes.origin]\ngit-host = "github"\nvisibility = "public"\n')
    projects.git("-C", a, "remote", "set-url", "origin", "git@github.com:me/a.git")
    assert run("--all").listing == ["🏠 🐙 🌐 a  main  ✔"]


def test_origin_on_a_git_host_its_settings_say_nothing_of_is_reported(projects, run):
    a = projects.pushed_repo("a")
    projects.git("-C", a, "remote", "set-url", "origin", "git@github.com:me/a.git")
    assert run().listing == [
        "🏠 🐙    a  main  ✘ 🔧 .config/ianf-repo-tools.toml doesn't set"
        " remotes.origin.git-host or remotes.origin.visibility"
    ]


def test_origin_whose_settings_name_its_git_host_but_not_who_can_see_it_is_reported(projects, run):
    a = projects.pushed_repo("a")
    on_github(projects, a)
    projects.git("-C", a, "remote", "set-url", "origin", "git@github.com:me/a.git")
    assert run().listing == [
        "🏠 🐙    a  main  ✘ 🔧 .config/ianf-repo-tools.toml doesn't set remotes.origin.visibility"
    ]


def test_origin_on_a_git_host_repo_tools_has_no_adapter_for_needs_no_settings(projects, run):
    a = projects.pushed_repo("a")
    projects.git("-C", a, "remote", "set-url", "origin", "git@gitlab.com:me/a.git")
    assert run("--all").listing == ["🏠 🦊    a  main  ✔"]


def test_origin_on_another_git_host_is_reported(projects, run):
    a = projects.pushed_repo("a")
    on_github(projects, a)
    projects.git("-C", a, "remote", "set-url", "origin", "git@bitbucket.org:me/a.git")
    assert run().listing == [f"🏠 🧺    a  main  ✘ 🧭 origin is on Bitbucket, {ELSEWHERE}"]


def test_origin_on_another_git_host_or_server_or_a_path_is_reported(projects, run):
    a = projects.pushed_repo("a")
    on_github(projects, a)
    assert run().listing == [
        f"🏠 ❔    a  main  ✘ 🧭 origin is on another git host or server, {ELSEWHERE}"
    ]


def test_remotes_without_origin_are_reported(projects, run):
    a = projects.pushed_repo("a")
    on_github(projects, a)
    projects.git("-C", a, "remote", "rename", "origin", "upstream")
    assert run().listing == [f"🏠 ❔    a  main  ✘ 🧭 no origin remote, {ELSEWHERE}"]


def test_settings_that_name_no_git_host_leave_origin_wherever_it_is(projects, run):
    projects.pushed_repo("a")
    assert run("--all").listing == ["🏠 ❔    a  main  ✔"]


def test_with_no_remote_only_the_missing_remote_is_reported(projects, run):
    projects.local_repo("a")
    assert run().listing == ["🏠 🔌    a  main  ✘ 🔌 no remote"]


def test_a_git_host_that_cant_be_used_is_a_settings_problem_shown_alone(projects, run):
    a = projects.pushed_repo("a")
    put_origin_on(projects, a, '[remotes.origin]\ngit-host = "gitlab"\n')
    assert run().listing == [
        "🏠 ❔    a  main  ✘ 🔧 .config/ianf-repo-tools.toml: remotes.origin.git-host must be"
        " one of github, bitbucket, none"
    ]


def test_a_remote_other_than_origin_cant_be_set_yet(projects, run):
    a = projects.pushed_repo("a")
    put_origin_on(projects, a, '[remotes.mirror]\ngit-host = "github"\n')
    assert run().listing == [
        "🏠 ❔    a  main  ✘ 🔧 .config/ianf-repo-tools.toml: remotes can only set origin for now,"
        " not mirror"
    ]


def test_a_local_only_repository_with_no_remote_is_clean(projects, run):
    projects.git_host("none")
    projects.local_repo("a")
    assert run("--all").listing == ["🏠 💻    a  main  ✔"]


def test_a_remote_on_a_local_only_repository_is_reported(projects, run):
    a = projects.pushed_repo("a")
    put_origin_on(projects, a, '[remotes.origin]\ngit-host = "none"\n')
    assert run().listing == [
        "🏠 ❔    a  main  ✘ 🧭 has a remote, though .config/ianf-repo-tools.toml keeps it local"
    ]


def test_a_local_only_repository_with_pr_integration_is_a_settings_problem(projects, run):
    projects.integration("pr-rebase")
    projects.git_host("none")
    projects.local_repo("a")
    assert run().listing == [
        '📏 💻    a  main  ✘ 🔧 .config/ianf-repo-tools.toml: remotes.origin.git-host = "none"'
        ' needs integration = "direct", as there are no pull requests without a remote'
    ]


def test_a_visibility_that_cant_be_used_is_a_settings_problem(projects, run):
    a = projects.pushed_repo("a")
    put_origin_on(projects, a, '[remotes.origin]\ngit-host = "github"\nvisibility = "secret"\n')
    assert run().listing == [
        "🏠 ❔    a  main  ✘ 🔧 .config/ianf-repo-tools.toml: remotes.origin.visibility must be"
        " one of public, private"
    ]


def test_a_visibility_for_a_local_only_repository_is_a_settings_problem(projects, run):
    a = projects.pushed_repo("a")
    put_origin_on(projects, a, '[remotes.origin]\ngit-host = "none"\nvisibility = "private"\n')
    assert run().listing == [
        "🏠 ❔    a  main  ✘ 🔧 .config/ianf-repo-tools.toml: remotes.origin.visibility can't be"
        ' set with git-host = "none", as it\'s never published'
    ]
