"""Behaviour of repo-fix, with claude and github replaced by scripts that record their calls."""

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from repo_list import fix

COMMITS = """git add -A && git commit -qm "Fake commit" && echo '{"result": "✅ Committed."}'"""
DOES_NOTHING = """printf '%s' '{"result": "🛑 Stopped.\\nThe check failed."}'"""
REWRITES = """git add -A && git commit -q --amend -m "Rewritten" && echo '{"result": "✅"}'"""
LEAVES_A_FILE = """git add f && git commit -qm "Fake commit" && echo '{"result": "Kept g out."}'"""

PUBLISHES = """git init -q --bare "$REMOTE" && git -C "$2" remote add origin "$REMOTE" \
&& git -C "$2" push -q -u origin HEAD && echo 'Created me/thing (public)' \
&& echo '✅ Published.' && echo 'https://github.com/me/thing'"""
REFUSES = """echo '⚠️ Not today.' >&2; exit 1"""

# The fake packagist changes what the fake Packagist lacks, in the file conftest's packagist reads.
PACKAGIST = """python3 - "$@" <<'EOF'
import json, os, sys
command, directory = sys.argv[1:3]
name = json.load(open(os.path.join(directory, "composer.json")))["name"]
url = f"https://packagist.org/packages/{name}"
lacking = json.load(open(os.environ["PACKAGIST_STATE"]))
if command == "publish" and name in lacking:
    print(f"➖ Already published: {url}")
elif command == "publish":
    lacking[name] = []
    print(f"Submitted {name}", "Added the Packagist webhook", "✅ Published.", url, sep="\\n")
elif lacking[name]:
    lacking[name] = []
    print(f"Asked Packagist to update {name}", "✅ Updated.", url, sep="\\n")
else:
    print(f"➖ Already up to date: {url}")
json.dump(lacking, open(os.environ["PACKAGIST_STATE"], "w"))
EOF"""


class Fakes:
    """Stand-ins for claude and github, each a script that logs its arguments and directory."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.dir = tmp_path / "fakes"
        self.dir.mkdir()
        self.remote = tmp_path / "remotes" / "published.git"
        self.packagist_state = tmp_path / "packagist.json"
        self.monkeypatch = monkeypatch
        self.claude(COMMITS)
        self.github(PUBLISHES)
        self.packagist(PACKAGIST)

    def claude(self, action: str) -> None:
        self.monkeypatch.setattr(fix, "CLAUDE", str(self._script("claude", action)))

    def github(self, action: str) -> None:
        self.monkeypatch.setattr(fix, "GITHUB", str(self._script("github", action)))

    def packagist(self, action: str) -> None:
        self.monkeypatch.setattr(fix, "PACKAGIST", str(self._script("packagist", action)))

    def calls(self, name: str) -> list[list[str]]:
        """Each call's directory, then its arguments."""
        log = self.dir / f"{name}.log"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def _script(self, name: str, action: str) -> Path:
        script = self.dir / name
        log = self.dir / f"{name}.log"
        script.write_text(
            "#!/bin/sh\n"
            f"REMOTE='{self.remote}'\n"
            f"export PACKAGIST_STATE='{self.packagist_state}'\n"
            f"python3 -c 'import json, os, sys; print(json.dumps([os.getcwd(), *sys.argv[1:]]))'"
            f' "$@" >> "{log}"\n'
            f"{action}\n"
        )
        script.chmod(0o755)
        return script


@pytest.fixture
def fakes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, projects) -> Fakes:
    """The fakes, and a commit skill in HOME whose references are a symlink to elsewhere."""
    shared = tmp_path / "skills-repo" / "shared" / "references"
    shared.mkdir(parents=True)
    (shared / "guide.md").write_text("guide\n")
    skill = Path.home() / ".claude" / "skills" / "commit"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: commit\n---\n")
    (skill / "references").symlink_to(shared)
    return Fakes(tmp_path, monkeypatch)


@dataclass
class Result:
    progress: list[str]
    """What it did, repository by repository."""
    listing: list[str]
    """repo-list's lines for the state it left."""
    status: int


@pytest.fixture
def repo_fix(capsys: pytest.CaptureFixture[str], fakes):
    def repo_fix(*args: str | Path) -> Result:
        status = fix.main([str(a) for a in args])
        out = capsys.readouterr().out.rstrip("\n")
        sections = out.split("\n\n")
        progress = sections[0].splitlines() if len(sections) == 3 else []
        return Result(progress, sections[-2].splitlines(), status)

    return repo_fix


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def subjects(repo: Path, revisions: str = "HEAD") -> list[str]:
    return git(repo, "log", "--reverse", "--format=%s", revisions).splitlines()


# --- Uncommitted work


def test_uncommitted_work_is_committed_by_running_the_commit_skill_in_the_repository(
    projects, fakes, repo_fix
):
    a = projects.pushed_repo("a")
    (a / "g").write_text("new\n")
    result = repo_fix()
    [(directory, *args)] = fakes.calls("claude")
    assert Path(directory) == a
    assert args[:2] == ["-p", "/commit"]
    assert subjects(a) == ["init", "Fake commit"]
    head = git(a, "rev-parse", "--short", "HEAD")
    assert result.progress[:2] == ["a", f"  ✔ Committed {head} Fake commit"]


def test_the_commit_skill_may_read_the_files_its_symlinks_lead_to(
    projects, fakes, repo_fix, tmp_path
):
    a = projects.pushed_repo("a")
    (a / "g").write_text("new\n")
    repo_fix()
    [(_, *args)] = fakes.calls("claude")
    allowed = [args[i + 1] for i, arg in enumerate(args) if arg == "--add-dir"]
    assert str(tmp_path / "skills-repo" / "shared" / "references") in allowed


def test_the_new_commits_are_pushed(projects, repo_fix):
    a = projects.pushed_repo("a")
    (a / "g").write_text("new\n")
    result = repo_fix()
    assert subjects(projects.origin(a)) == ["init", "Fake commit"]
    assert result.listing == ["✔ a"]
    assert result.status == 0


def test_a_commit_run_that_leaves_work_uncommitted_fails_with_what_claude_said_and_pushes_nothing(
    projects, fakes, repo_fix
):
    a = projects.pushed_repo("a")
    (a / "f").write_text("change\n")
    (a / "g").write_text("new\n")
    fakes.claude(LEAVES_A_FILE)
    result = repo_fix()
    assert result.progress[-2:] == ["  ✘ Commit left work uncommitted:", "    Kept g out."]
    assert subjects(projects.origin(a)) == ["init"]
    assert result.status == 1


def test_a_commit_run_that_commits_nothing_fails_with_what_claude_said(projects, fakes, repo_fix):
    a = projects.pushed_repo("a")
    (a / "g").write_text("new\n")
    fakes.claude(DOES_NOTHING)
    result = repo_fix()
    assert result.progress == [
        "a",
        "  ✘ Commit failed:",
        "    🛑 Stopped.",
        "    The check failed.",
    ]
    assert result.listing == ["✘ a  📝 1 uncommitted file"]


def test_a_commit_run_that_rewrites_earlier_commits_fails_and_pushes_nothing(
    projects, fakes, repo_fix
):
    a = projects.pushed_repo("a")
    projects.commit(a, "local")
    start = git(a, "rev-parse", "--short", "HEAD")
    (a / "g").write_text("new\n")
    fakes.claude(REWRITES)
    result = repo_fix()
    assert result.progress == [
        "a",
        f"  ✘ Commit failed: it rewrote commits made before it; the branch was at {start}",
    ]
    assert subjects(projects.origin(a)) == ["init"]


def test_work_on_a_detached_head_is_not_committed(projects, fakes, repo_fix):
    a = projects.pushed_repo("a")
    git(a, "checkout", "-q", "--detach")
    (a / "g").write_text("new\n")
    result = repo_fix()
    assert fakes.calls("claude") == []
    assert result.progress == ["a", "  ✘ Not committing: HEAD is detached"]


def test_work_during_a_merge_is_not_committed(projects, fakes, repo_fix):
    a = projects.pushed_repo("a")
    (a / "g").write_text("new\n")
    (a / ".git" / "MERGE_HEAD").write_text(git(a, "rev-parse", "HEAD") + "\n")
    result = repo_fix()
    assert fakes.calls("claude") == []
    assert result.progress == ["a", "  ✘ Not committing: a merge is in progress"]


def test_without_the_commit_skill_nothing_is_committed(projects, fakes, repo_fix):
    a = projects.pushed_repo("a")
    (a / "g").write_text("new\n")
    skill = Path.home() / ".claude" / "skills" / "commit"
    (skill / "SKILL.md").unlink()
    result = repo_fix()
    assert fakes.calls("claude") == []
    assert result.progress == ["a", f"  ✘ Not committing: no commit skill in {skill}"]


# --- Pushing and pulling


def test_unpushed_commits_are_pushed_to_the_branch_upstream(projects, repo_fix):
    a = projects.pushed_repo("a")
    projects.commit(a, "local")
    result = repo_fix()
    assert result.progress == ["a", "  ✔ Pushed main to origin"]
    assert subjects(projects.origin(a)) == ["init", "local"]


def test_a_branch_without_an_upstream_is_pushed_to_the_only_remote_and_tracks_it(
    projects, repo_fix
):
    a = projects.pushed_repo("a")
    git(a, "checkout", "-qb", "feature")
    projects.commit(a, "feature work")
    result = repo_fix()
    assert result.progress == ["a", "  ✔ Pushed feature to origin, now its upstream"]
    assert git(a, "rev-parse", "--abbrev-ref", "feature@{u}") == "origin/feature"


def test_a_branch_without_an_upstream_is_not_pushed_when_there_are_several_remotes(
    projects, repo_fix
):
    a = projects.pushed_repo("a")
    git(a, "remote", "add", "second", str(projects.origin(a)))
    git(a, "checkout", "-qb", "feature")
    projects.commit(a, "feature work")
    result = repo_fix()
    assert result.progress == [
        "a",
        "  ✘ Not pushing feature: it has no upstream, and 2 remotes to choose from",
    ]


def test_branches_behind_their_upstream_are_fast_forwarded_whether_checked_out_or_not(
    projects, repo_fix
):
    a = projects.pushed_repo("a")
    git(a, "branch", "--track", "other", "origin/main")
    projects.push_from_elsewhere(a)
    result = repo_fix()
    assert result.progress == [
        "a",
        "  ✔ Fast-forwarded main to origin/main",
        "  ✔ Fast-forwarded other to origin/main",
    ]
    assert subjects(a, "main") == subjects(a, "other") == ["init", "ahead"]
    assert (a / "f").read_text() == "init\nahead\n"


def test_a_branch_that_has_diverged_from_its_upstream_is_neither_pushed_nor_pulled(
    projects, repo_fix
):
    a = projects.pushed_repo("a")
    projects.push_from_elsewhere(a)
    projects.commit(a, "local")
    result = repo_fix()
    assert result.progress == ["a", "  ✘ Not syncing main: it has diverged from origin/main"]
    assert subjects(a) == ["init", "local"]


def test_a_rejected_push_is_reported_with_git_error(projects, repo_fix):
    a = projects.pushed_repo("a")
    projects.commit(a, "local")
    hook = projects.origin(a) / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho 'no pushing' >&2\nexit 1\n")
    hook.chmod(0o755)
    result = repo_fix()
    assert result.progress[:2] == ["a", "  ✘ Push of main failed:"]
    assert any("no pushing" in line for line in result.progress)


def test_a_repository_whose_fetch_fails_is_neither_pushed_nor_pulled(projects, repo_fix):
    a = projects.pushed_repo("a")
    projects.commit(a, "local")
    git(a, "remote", "set-url", "origin", str(projects.remotes / "missing.git"))
    result = repo_fix()
    assert result.progress == []
    assert result.listing == ["✘ a  📤 1 unpushed on main  📡 fetch failed"]


# --- Publishing


def test_a_repository_without_a_remote_is_published_with_github_publish(projects, fakes, repo_fix):
    a = projects.local_repo("a")
    result = repo_fix()
    assert [call[1:] for call in fakes.calls("github")] == [["publish", str(a)]]
    assert result.progress == [
        "a",
        "  ✔ Published:",
        "    Created me/thing (public)",
        "    https://github.com/me/thing",
    ]
    assert result.listing == ["✔ a"]


def test_the_no_ci_wait_flag_is_passed_to_github_publish(projects, fakes, repo_fix):
    a = projects.local_repo("a")
    repo_fix("--no-ci-wait")
    assert [call[1:] for call in fakes.calls("github")] == [["publish", str(a), "--no-ci-wait"]]


def test_a_repository_is_committed_before_it_is_published(projects, fakes, repo_fix):
    a = projects.local_repo("a")
    (a / "g").write_text("new\n")
    repo_fix()
    assert subjects(fakes.remote) == ["init", "Fake commit"]


def test_a_failed_publish_is_reported_with_its_output(projects, fakes, repo_fix):
    projects.local_repo("a")
    fakes.github(REFUSES)
    result = repo_fix()
    assert result.progress == ["a", "  ✘ Publish failed:", "    ⚠️ Not today."]
    assert result.listing == ["✘ a  🔌 no remote"]


def test_other_branches_are_pushed_once_the_repository_is_published(projects, fakes, repo_fix):
    a = projects.local_repo("a")
    git(a, "branch", "feature")
    git(a, "checkout", "-q", "feature")
    projects.commit(a, "feature work")
    git(a, "checkout", "-q", "main")
    result = repo_fix()
    assert result.progress[-1] == "  ✔ Pushed feature to origin, now its upstream"
    assert result.listing == ["✔ a"]


# --- Packagist


def test_a_package_not_on_packagist_is_published_there(projects, fakes, repo_fix):
    a = projects.package("a")
    result = repo_fix("-p")
    assert result.progress == [
        "a",
        "  ✔ Published on Packagist:",
        "    Submitted me/a",
        "    Added the Packagist webhook",
        "    https://packagist.org/packages/me/a",
    ]
    assert [call[1:] for call in fakes.calls("packagist")] == [
        ["publish", str(a)],
        ["update", str(a)],
    ]
    assert (result.listing, result.status) == (["✔ a"], 0)


def test_a_package_packagist_lacks_versions_of_is_updated_there(
    projects, packagist, fakes, repo_fix
):
    projects.package("a")
    packagist.has("me/a", lacking=["v0.2.0"])
    result = repo_fix("-p")
    assert result.progress == [
        "a",
        "  ✔ Updated on Packagist:",
        "    Asked Packagist to update me/a",
        "    https://packagist.org/packages/me/a",
    ]
    assert (result.listing, result.status) == (["✔ a"], 0)


def test_a_package_packagist_is_up_to_date_on_is_left_alone(projects, packagist, fakes, repo_fix):
    projects.package("a")
    packagist.has("me/a")
    result = repo_fix("-p")
    assert (result.progress, result.listing) == ([], ["✔ a"])
    assert fakes.calls("packagist") == []


def test_packagist_is_checked_after_pushing_so_it_is_compared_with_what_was_pushed(
    projects, packagist, fakes, repo_fix
):
    a = projects.package("a")
    projects.commit(a, "local")
    result = repo_fix("-p")
    assert result.progress[:2] == ["a", "  ✔ Pushed main to origin"]
    assert result.progress[2] == "  ✔ Published on Packagist:"


def test_a_failed_packagist_publish_is_reported_and_no_update_is_tried(projects, fakes, repo_fix):
    a = projects.package("a")
    fakes.packagist(REFUSES)
    result = repo_fix("-p")
    assert result.progress == ["a", "  ✘ Packagist publish failed:", "    ⚠️ Not today."]
    assert [call[1:] for call in fakes.calls("packagist")] == [["publish", str(a)]]
    assert (result.listing, result.status) == (["✘ a  🐘 not on Packagist"], 1)


def test_without_the_packagist_flag_packagist_is_left_alone(projects, fakes, repo_fix):
    projects.package("a")
    result = repo_fix()
    assert (result.progress, result.listing) == ([], ["✔ a"])
    assert fakes.calls("packagist") == []


# --- Folders that are not repositories


def test_a_folder_of_files_is_left_alone_by_default(projects, fakes, repo_fix):
    (projects.root / "notes").mkdir()
    (projects.root / "notes" / "todo").write_text("x\n")
    result = repo_fix()
    assert result.progress == []
    assert result.listing == ["✘ notes  📁 not a git repository"]
    assert fakes.calls("claude") == fakes.calls("github") == []


def test_the_init_flag_makes_a_folder_of_files_a_published_repository(projects, fakes, repo_fix):
    notes = projects.root / "notes"
    notes.mkdir()
    (notes / "todo").write_text("x\n")
    result = repo_fix("--init")
    assert result.progress[:2] == ["notes", "  ✔ Initialised a git repository"]
    assert subjects(fakes.remote) == ["Fake commit"]
    assert result.listing == ["✔ notes"]


# --- What it leaves alone


def test_stashes_and_commits_on_a_detached_head_are_left_for_you(projects, fakes, repo_fix):
    a = projects.pushed_repo("a")
    (a / "f").write_text("change\n")
    git(a, "stash", "-q")
    git(a, "checkout", "-q", "--detach")
    projects.commit(a, "lost")
    result = repo_fix()
    assert result.progress == []
    assert result.listing == ["✘ a  👻 1 commit on detached HEAD  📦 1 stash"]
    assert result.status == 1


def test_a_clean_repository_has_nothing_done_to_it(projects, fakes, repo_fix):
    projects.pushed_repo("a")
    result = repo_fix()
    assert (result.progress, result.listing, result.status) == ([], ["✔ a"], 0)
    assert fakes.calls("claude") == fakes.calls("github") == []


# --- Which repositories


def test_a_path_to_a_repository_fixes_only_that_repository(projects, repo_fix):
    a = projects.pushed_repo("a")
    b = projects.pushed_repo("b")
    projects.commit(a, "local")
    projects.commit(b, "local")
    result = repo_fix(b)
    assert result.progress == ["b", "  ✔ Pushed main to origin"]
    assert result.listing == ["✔ b"]
    assert subjects(projects.origin(a)) == ["init"]


def test_a_path_to_a_folder_fixes_every_repository_under_it(projects, repo_fix):
    (projects.root / "group").mkdir()
    a = projects.pushed_repo("group/a")
    b = projects.pushed_repo("group/b")
    projects.commit(a, "local")
    projects.commit(b, "local")
    result = repo_fix(projects.root / "group")
    assert result.progress == ["a", "  ✔ Pushed main to origin", "b", "  ✔ Pushed main to origin"]
    assert result.listing == ["✔ a", "✔ b"]


def test_with_no_path_it_fixes_every_repository_in_projects_wherever_it_is_run_from(
    projects, repo_fix, monkeypatch
):
    (projects.root / "group").mkdir()
    a = projects.pushed_repo("group/a")
    b = projects.pushed_repo("b")
    projects.commit(a, "local")
    projects.commit(b, "local")
    monkeypatch.chdir(a)
    result = repo_fix()
    assert result.progress == [
        "b",
        "  ✔ Pushed main to origin",
        "group/a",
        "  ✔ Pushed main to origin",
    ]
    assert result.listing == ["✔ b", "✔ group/a"]


# --- Colour


def test_on_a_terminal_the_path_marks_failures_and_details_are_coloured_as_repo_list_does(
    projects, fakes, repo_fix, monkeypatch
):
    monkeypatch.setenv("FORCE_COLOR", "1")
    (projects.root / "group").mkdir()
    a = projects.pushed_repo("group/a")
    (a / "f").write_text("change\n")
    (a / "g").write_text("new\n")
    fakes.claude(LEAVES_A_FILE)
    result = repo_fix()
    head = git(a, "rev-parse", "--short", "HEAD")
    assert result.progress == [
        "\x1b[38;5;246mgroup/\x1b[0m\x1b[1ma\x1b[0m",
        f"  \x1b[32m✔\x1b[0m Committed {head} Fake commit",
        "  \x1b[31m✘\x1b[0m \x1b[33mCommit left work uncommitted:\x1b[0m",
        "    \x1b[38;5;246mKept g out.\x1b[0m",
    ]


def test_no_color_turns_colour_off_even_when_forced(projects, fakes, repo_fix, monkeypatch):
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.setenv("NO_COLOR", "1")
    a = projects.pushed_repo("a")
    (a / "f").write_text("change\n")
    (a / "g").write_text("new\n")
    fakes.claude(LEAVES_A_FILE)
    assert repo_fix().progress == [
        "a",
        f"  ✔ Committed {git(a, 'rev-parse', '--short', 'HEAD')} Fake commit",
        "  ✘ Commit left work uncommitted:",
        "    Kept g out.",
    ]
