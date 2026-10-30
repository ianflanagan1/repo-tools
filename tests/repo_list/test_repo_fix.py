"""Behaviour of repo-fix, with claude, github, packagist, npmjs and devbox replaced by scripts that
record their calls."""

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest
from cli_kit.models import claude_code

from repo_list import fix
from repo_list.plugins import github, lock, npm, packagist
from repo_list.plugins import release as release_plugin

COMMITS = """git add --all && git commit --quiet --message "Fake commit" \
&& echo '{"result": "✅ Committed."}'"""
DOES_NOTHING = """printf '%s' '{"result": "🛑 Stopped.\\nThe check failed."}'"""
REWRITES = """git add --all && git commit --quiet --amend --message "Rewritten" \
&& echo '{"result": "✅"}'"""
LEAVES_A_FILE = """git add f && git commit --quiet --message "Fake commit" \
&& echo '{"result": "Kept g out."}'"""

PUBLISHES = """git init --quiet --bare "$REMOTE" && git -C "$2" remote add origin "$REMOTE" \
&& git -C "$2" push --quiet --set-upstream origin HEAD && echo 'Created me/thing (public)' \
&& echo '✅ Published.' && echo 'https://github.com/me/thing'"""
REFUSES = """echo '⚠️ Not today.' >&2; exit 1"""
# The fake release tags HEAD as v1.0.1, as the next patch version after v1.0.0, and pushes it.
RELEASES = """git -C "$2" tag v1.0.1 && git -C "$2" push --quiet origin v1.0.1 \
&& echo 'Tagged HEAD as v1.0.1' && echo 'Pushed v1.0.1' && echo '✅ Released v1.0.1.'"""
GITHUB = f"""case "$1" in release) {RELEASES} ;; *) {PUBLISHES} ;; esac"""

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

# The fake npmjs changes what the fake npm lacks, in the file conftest's npm reads.
NPMJS = """python3 - "$@" <<'EOF'
import json, os, sys
command, directory = sys.argv[1:3]
name = json.load(open(os.path.join(directory, "package.json")))["name"]
url = f"https://www.npmjs.com/package/{name}"
lacking = json.load(open(os.environ["NPM_STATE"]))
if command == "publish":
    lacking[name] = []
    print(f"Published {name}@0.1.0", "✅ Published.", url, sep="\\n")
elif lacking[name]:
    lacking[name] = []
    print("✅ Published.", url, sep="\\n")
else:
    print(f"➖ Already published: {url}")
json.dump(lacking, open(os.environ["NPM_STATE"], "w"))
EOF"""

# The fake devbox runs a fake uv, whose uv.lock is JSON: the git source of each locked package, and
# the commit it's locked at. An upgrade locks each at its source's HEAD.
UV = """python3 - "$@" <<'EOF'
import json, subprocess, sys
locked = json.load(open("uv.lock"))
heads = {
    name: subprocess.run(
        ["git", "--git-dir", source, "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    for name, source in locked["sources"].items()
}
print(f"Resolved {len(heads)} packages in 1ms", file=sys.stderr)
for name, head in heads.items():
    if locked["at"][name] != head:
        print(f"Update {name} {locked['at'][name]} -> {head}", file=sys.stderr)
if "--dry-run" not in sys.argv:
    json.dump({"sources": locked["sources"], "at": heads}, open("uv.lock", "w"))
EOF"""


class Fakes:
    """Stand-ins for claude, github, packagist, npmjs and devbox, each a script that logs its
    arguments and directory."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.dir = tmp_path / "fakes"
        self.dir.mkdir()
        self.remote = tmp_path / "remotes" / "published.git"
        self.packagist_state = tmp_path / "packagist.json"
        self.npm_state = tmp_path / "npm.json"
        self.monkeypatch = monkeypatch
        self.claude(COMMITS)
        self.github(GITHUB)
        # Every origin is a path here, so it's released as if it were on GitHub.
        monkeypatch.setattr(release_plugin, "command_for", lambda url: github.GITHUB)
        self.packagist(PACKAGIST)
        self.npmjs(NPMJS)
        self.devbox(UV)

    def claude(self, action: str) -> None:
        self.monkeypatch.setattr(claude_code, "CLAUDE", str(self._script("claude", action)))

    def github(self, action: str) -> None:
        self.monkeypatch.setattr(github, "GITHUB", str(self._script("github", action)))

    def packagist(self, action: str) -> None:
        self.monkeypatch.setattr(packagist, "PACKAGIST", str(self._script("packagist", action)))

    def npmjs(self, action: str) -> None:
        self.monkeypatch.setattr(npm, "NPMJS", str(self._script("npmjs", action)))

    def devbox(self, action: str) -> None:
        self.monkeypatch.setattr(lock, "DEVBOX", str(self._script("devbox", action)))

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
            f"export NPM_STATE='{self.npm_state}'\n"
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
    skill = Path.home() / ".claude" / "skills" / "ianf-commit"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: ianf-commit\n---\n")
    (skill / "references").symlink_to(shared)
    return Fakes(tmp_path, monkeypatch)


@dataclass
class Result:
    progress: list[str]
    """What it did, repository by repository."""
    listing: list[str]
    """repo-list's lines for the state it left."""
    summary: str
    """repo-list's total for the state it left."""
    status: int


@pytest.fixture
def repo_fix(capsys: pytest.CaptureFixture[str], fakes):
    def repo_fix(*args: str | Path) -> Result:
        status = fix.main([str(a) for a in args])
        out = capsys.readouterr().out.rstrip("\n")
        *sections, summary = [s.splitlines() for s in out.split("\n\n")]
        # What was done is indented under each path; repo-list's lines never are.
        done = sections and any(line.startswith("  ") for line in sections[0])
        progress = sections.pop(0) if done else []
        listing = sections[0] if sections else []
        return Result(progress, listing, summary[0], status)

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
    assert args[:2] == ["--print", "/ianf-commit"]
    assert subjects(a) == ["init", "Fake commit"]
    head = git(a, "rev-parse", "--short", "HEAD")
    assert result.progress[:3] == [
        "a",
        "  … Committing with Claude Code's /ianf-commit, which can take a few minutes",
        f"  ✔ Committed {head} Fake commit",
    ]


def test_each_step_that_can_take_a_while_says_so_before_it_starts(projects, fakes, repo_fix):
    projects.local_repo("a")
    result = repo_fix()
    assert result.progress[:3] == [
        "a",
        "  … Publishing with `github publish`, then waiting for CI",
        "  ✔ Published:",
    ]


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
    assert result.summary == "✔ All 1 clean"
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
        "  … Committing with Claude Code's /ianf-commit, which can take a few minutes",
        "  ✘ Commit failed:",
        "    🛑 Stopped.",
        "    The check failed.",
    ]
    assert result.listing == ["🏠 ❔    a  main  ✘ 📝 1 uncommitted file"]


def test_a_commit_run_whose_claude_cannot_start_fails_with_why(
    projects, fakes, repo_fix, tmp_path, monkeypatch
):
    a = projects.pushed_repo("a")
    (a / "g").write_text("new\n")
    monkeypatch.setattr(claude_code, "CLAUDE", str(tmp_path / "missing"))
    result = repo_fix()
    assert result.progress[2] == "  ✘ Commit failed:"
    assert "No such file" in result.progress[3]
    assert subjects(a) == ["init"]


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
        "  … Committing with Claude Code's /ianf-commit, which can take a few minutes",
        f"  ✘ Commit failed: it rewrote commits made before it; HEAD was at {start}",
    ]
    assert subjects(projects.origin(a)) == ["init"]


def test_work_on_a_detached_head_is_committed_there(projects, fakes, repo_fix):
    a = projects.pushed_repo("a")
    git(a, "checkout", "--quiet", "--detach")
    (a / "g").write_text("new\n")
    result = repo_fix()
    assert subjects(a) == ["init", "Fake commit"]
    head = git(a, "rev-parse", "--short", "HEAD")
    assert result.progress == [
        "a",
        "  … Committing with Claude Code's /ianf-commit, which can take a few minutes",
        f"  ✔ Committed {head} Fake commit",
    ]
    assert result.listing == [f"🏠 ❔    a  @{head}  ✘ 👻 1 commit on detached HEAD"]


def test_with_pr_integration_work_on_the_trunk_is_not_committed_as_it_belongs_on_a_branch(
    projects, fakes, repo_fix
):
    projects.integration("pr-merge")
    a = projects.pushed_repo("a")
    (a / "g").write_text("new\n")
    result = repo_fix()
    assert fakes.calls("claude") == []
    assert result.progress == [
        "a",
        "  ✘ Not committing on main: work goes on a branch, for a pull request",
    ]


def test_with_pr_integration_work_on_a_branch_is_committed_and_pushed(projects, fakes, repo_fix):
    projects.integration("pr-merge")
    a = projects.pushed_repo("a")
    git(a, "checkout", "--quiet", "-b", "feature")
    (a / "g").write_text("new\n")
    result = repo_fix()
    assert result.progress[-1] == "  ✔ Pushed feature to origin, now its upstream"
    assert subjects(projects.origin(a), "feature") == ["init", "Fake commit"]


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
    skill = Path.home() / ".claude" / "skills" / "ianf-commit"
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


def test_with_pr_integration_a_branch_without_an_upstream_is_pushed_to_the_only_remote(
    projects, repo_fix
):
    projects.integration("pr-merge")
    a = projects.pushed_repo("a")
    git(a, "checkout", "--quiet", "-b", "feature")
    projects.commit(a, "feature work")
    result = repo_fix()
    assert result.progress == ["a", "  ✔ Pushed feature to origin, now its upstream"]
    assert git(a, "rev-parse", "--abbrev-ref", "feature@{u}") == "origin/feature"


def test_a_branch_without_an_upstream_is_not_pushed_when_there_are_several_remotes(
    projects, repo_fix
):
    projects.integration("pr-merge")
    a = projects.pushed_repo("a")
    git(a, "remote", "add", "second", str(projects.origin(a)))
    git(a, "checkout", "--quiet", "-b", "feature")
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


def test_with_direct_integration_a_trunk_that_has_diverged_from_its_upstream_is_rebased_onto_it(
    projects, repo_fix
):
    a = projects.pushed_repo("a")
    projects.push_from_elsewhere(a)
    (a / "g").write_text("local\n")
    git(a, "add", "g")
    git(a, "commit", "--quiet", "--message", "local")
    result = repo_fix()
    assert result.progress == [
        "a",
        "  ✔ Rebased main onto origin/main",
        "  ✔ Pushed main to origin",
    ]
    assert subjects(projects.origin(a)) == ["init", "ahead", "local"]


def test_a_trunk_whose_rebase_onto_its_upstream_conflicts_is_left_as_it_was(projects, repo_fix):
    a = projects.pushed_repo("a")
    projects.push_from_elsewhere(a)
    projects.commit(a, "local")
    result = repo_fix()
    assert result.progress == [
        "a",
        "  ✘ Rebase main onto origin/main stopped at a conflict, so it was undone",
    ]
    assert subjects(a) == ["init", "local"]
    assert git(a, "status", "--porcelain") == ""


def test_with_pr_integration_a_diverged_branch_is_neither_pushed_nor_pulled(projects, repo_fix):
    projects.integration("pr-merge")
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
    assert result.listing == ["🏠 ❔    a  main  ✘ 📤 1 unpushed on main  📡 fetch failed"]


# --- Dependencies between repositories


def python_project(name: str, *pinned_from_git: str) -> str:
    sources = "".join(f'{d} = {{ git = "https://example.com/{d}" }}\n' for d in pinned_from_git)
    return (
        f'[project]\nname = "{name}"\ndependencies = {list(pinned_from_git)!r}\n\n'
        f"[tool.uv.sources]\n{sources}"
    )


def test_a_dependency_its_dependant_pins_is_fixed_before_it_and_its_own_dependency_first(
    projects, repo_fix
):
    for name, pinned in [("a", ["kit"]), ("b", []), ("kit", ["base"]), ("base", [])]:
        repo = projects.python_project(name, python_project(name, *pinned))
        projects.commit(repo, "local")
    result = repo_fix()
    assert [line for line in result.progress if not line.startswith(" ")] == [
        "base",
        "kit",
        "a",
        "b",
    ]


def test_repositories_that_pin_each_other_are_reported_and_fixed_in_name_order(projects, repo_fix):
    for name, pinned in [("a", ["b"]), ("b", ["a"])]:
        repo = projects.python_project(name, python_project(name, *pinned))
        projects.commit(repo, "local")
    result = repo_fix()
    assert result.progress == [
        "These depend on each other, so are fixed in name order: a, b",
        "a",
        "  ✔ Pushed main to origin",
        "b",
        "  ✔ Pushed main to origin",
    ]


# --- Worktrees and the trunk


def test_the_trunk_is_updated_before_a_worktree_is_rebased_onto_it(projects, fakes, repo_fix):
    a = projects.pushed_repo("a")
    wt = projects.worktree(a, "0-wt", "--detach")
    (wt / "g").write_text("wt work\n")
    git(wt, "add", "g")
    git(wt, "commit", "--quiet", "--message", "wt work")
    projects.push_from_elsewhere(a)
    result = repo_fix()
    assert result.progress == [
        "a",
        "  ✔ Fast-forwarded main to origin/main",
        "0-wt",
        "  ✔ Rebased onto main",
    ]
    assert subjects(wt) == ["init", "ahead", "wt work"]


def test_with_direct_integration_work_on_another_branch_is_never_pushed(projects, fakes, repo_fix):
    a = projects.pushed_repo("a")
    wt = projects.worktree(a, "a-wt", "-b", "feature")
    projects.commit(wt, "feature work")
    result = repo_fix()
    assert result.progress == []
    assert result.listing == ["🏠 ❔    a-wt  feature  ✘ 🛬 1 unmerged on feature"]
    assert git(projects.origin(a), "branch", "--list", "feature") == ""


def test_a_worktree_is_not_caught_up_with_a_trunk_that_failed_to_update(projects, fakes, repo_fix):
    a = projects.pushed_repo("a")
    projects.commit(a, "two")
    wt = projects.root / "a-wt"
    git(a, "worktree", "add", "--quiet", "--detach", str(wt), "main~1")
    projects.push_from_elsewhere(a)
    result = repo_fix()
    assert result.progress == [
        "a",
        "  ✘ Rebase main onto origin/main stopped at a conflict, so it was undone",
        "a-wt",
        "  ✘ Not catching up with main: updating it failed",
    ]
    assert subjects(wt) == ["init"]


def test_a_worktree_whose_catching_up_conflicts_is_left_as_it_was(projects, fakes, repo_fix):
    a = projects.pushed_repo("a")
    wt = projects.worktree(a, "a-wt", "-b", "feature")
    projects.commit(wt, "feature work")
    projects.commit(a, "more")
    git(a, "push", "--quiet")
    result = repo_fix()
    assert result.progress == [
        "a-wt",
        "  ✘ Rebase onto main stopped at a conflict, so it was undone",
    ]
    assert subjects(wt) == ["init", "feature work"]
    assert git(wt, "status", "--porcelain") == ""


def test_a_rebase_that_fails_without_a_conflict_is_reported_as_failing(projects, repo_fix):
    a = projects.pushed_repo("a")
    projects.push_from_elsewhere(a)
    (a / "g").write_text("local\n")
    git(a, "add", "g")
    git(a, "commit", "--quiet", "--message", "local")
    hook = a / ".git" / "hooks" / "pre-rebase"
    hook.write_text("#!/bin/sh\necho refused by the hook >&2\nexit 1\n")
    hook.chmod(0o755)
    result = repo_fix()
    assert result.progress[:3] == [
        "a",
        "  ✘ Rebase main onto origin/main failed:",
        "    refused by the hook",
    ]
    assert subjects(a) == ["init", "local"]


def test_with_pr_rebase_integration_a_branch_is_rebased_on_the_remote_trunk_and_force_pushed(
    projects, fakes, repo_fix
):
    projects.integration("pr-rebase")
    a = projects.pushed_repo("a")
    git(a, "checkout", "--quiet", "-b", "feature")
    (a / "g").write_text("feature work\n")
    git(a, "add", "g")
    git(a, "commit", "--quiet", "--message", "feature work")
    git(a, "push", "--quiet", "--set-upstream", "origin", "feature")
    projects.push_from_elsewhere(a)
    result = repo_fix()
    assert result.progress == [
        "a",
        "  ✔ Fast-forwarded main to origin/main",
        "  ✔ Rebased onto origin/main",
        "  ✔ Pushed feature to origin, with a lease",
    ]
    assert subjects(projects.origin(a), "feature") == ["init", "ahead", "feature work"]


def test_with_pr_merge_integration_the_remote_trunk_is_merged_into_a_branch_and_pushed(
    projects, fakes, repo_fix
):
    projects.integration("pr-merge")
    a = projects.pushed_repo("a")
    git(a, "checkout", "--quiet", "-b", "feature")
    (a / "g").write_text("feature work\n")
    git(a, "add", "g")
    git(a, "commit", "--quiet", "--message", "feature work")
    git(a, "push", "--quiet", "--set-upstream", "origin", "feature")
    projects.push_from_elsewhere(a)
    result = repo_fix()
    assert result.progress == [
        "a",
        "  ✔ Fast-forwarded main to origin/main",
        "  ✔ Merged origin/main",
        "  ✔ Pushed feature to origin",
    ]
    assert git(projects.origin(a), "log", "-1", "--format=%P", "feature").count(" ") == 1


# --- Configuration


def test_a_repository_with_no_integration_set_is_left_alone(projects, fakes, repo_fix):
    projects.integration(None)
    a = projects.pushed_repo("a")
    projects.commit(a, "local")
    (a / "g").write_text("new\n")
    result = repo_fix()
    assert fakes.calls("claude") == []
    assert result.progress == [
        "a",
        "  ✘ 🔧 Set `integration` in .config/ianf-repo-tools.toml",
    ]
    assert subjects(projects.origin(a)) == ["init"]


def test_a_repository_given_an_integration_when_asked_is_fixed_in_that_integration(
    projects, fakes, repo_fix, terminal
):
    projects.integration(None)
    a = projects.pushed_repo("a")
    projects.commit(a, "local")
    terminal.answer("direct")
    result = repo_fix()
    assert "  ✔ Pushed main to origin" in result.progress
    assert "local" in subjects(projects.origin(a))


# --- Left alone


def test_a_directory_a_claude_code_session_is_busy_in_is_left_alone(projects, fakes, repo_fix):
    a = projects.pushed_repo("a")
    (a / "g").write_text("new\n")
    projects.claude_session(a, "s1", "busy")
    result = repo_fix()
    assert fakes.calls("claude") == []
    assert result.progress == ["a", "  ✘ Left alone: a Claude Code session is working here"]


def test_the_claude_code_session_running_repo_fix_does_not_stop_it(
    projects, fakes, repo_fix, monkeypatch
):
    a = projects.pushed_repo("a")
    (a / "g").write_text("new\n")
    projects.claude_session(a, "me", "busy")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "me")
    repo_fix()
    assert subjects(a) == ["init", "Fake commit"]


def test_a_repository_whose_settings_file_sets_skip_fix_is_left_alone(projects, fakes, repo_fix):
    a = projects.pushed_repo("a")
    (a / ".config" / "ianf-repo-tools.toml").write_text(
        'version = 1\nintegration = "direct"\nskip-fix = true\n'
    )
    result = repo_fix()
    assert fakes.calls("claude") == []
    assert result.progress == [
        "a",
        "  ✘ Left alone: skip-fix is set in .config/ianf-repo-tools.toml",
    ]


def test_a_skip_fix_set_to_false_is_fixed(projects, fakes, repo_fix):
    a = projects.pushed_repo("a")
    (a / ".config" / "ianf-repo-tools.toml").write_text(
        'version = 1\nintegration = "direct"\nskip-fix = false\n'
    )
    repo_fix()
    assert subjects(a) == ["init", "Fake commit"]


# --- Publishing


def test_a_repository_without_a_remote_is_published_with_github_publish(projects, fakes, repo_fix):
    a = projects.local_repo("a")
    result = repo_fix()
    assert [call[1:] for call in fakes.calls("github")] == [["publish", str(a)]]
    assert result.progress == [
        "a",
        "  … Publishing with `github publish`, then waiting for CI",
        "  ✔ Published:",
        "    Created me/thing (public)",
        "    https://github.com/me/thing",
    ]
    assert result.summary == "✔ All 1 clean"


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
    assert result.progress == [
        "a",
        "  … Publishing with `github publish`, then waiting for CI",
        "  ✘ Publish failed:",
        "    ⚠️ Not today.",
    ]
    assert result.listing == ["🏠 🔌    a  main  ✘ 🔌 no remote"]


def test_with_pr_integration_other_branches_are_pushed_once_the_repository_is_published(
    projects, fakes, repo_fix
):
    projects.integration("pr-merge")
    a = projects.local_repo("a")
    git(a, "branch", "feature")
    git(a, "checkout", "--quiet", "feature")
    projects.commit(a, "feature work")
    git(a, "checkout", "--quiet", "main")
    result = repo_fix()
    assert result.progress[-1] == "  ✔ Pushed feature to origin, now its upstream"
    assert result.summary == "✔ All 1 clean"


# --- Packagist


def test_a_package_not_on_packagist_is_published_there(projects, fakes, repo_fix):
    a = projects.package("a")
    result = repo_fix("--packagist")
    assert result.progress == [
        "a",
        "  … Running `packagist publish`",
        "  ✔ Published on Packagist:",
        "    Submitted me/a",
        "    Added the Packagist webhook",
        "    https://packagist.org/packages/me/a",
        "  … Running `packagist update`, which waits until Packagist has what was pushed",
    ]
    assert [call[1:] for call in fakes.calls("packagist")] == [
        ["publish", str(a)],
        ["update", str(a)],
    ]
    assert (result.summary, result.status) == ("✔ All 1 clean", 0)


def test_a_package_packagist_lacks_versions_of_is_updated_there(
    projects, packagist, fakes, repo_fix
):
    projects.package("a")
    packagist.has("me/a", lacking=["v0.2.0"])
    result = repo_fix("--packagist")
    assert result.progress == [
        "a",
        "  … Running `packagist publish`",
        "  … Running `packagist update`, which waits until Packagist has what was pushed",
        "  ✔ Updated on Packagist:",
        "    Asked Packagist to update me/a",
        "    https://packagist.org/packages/me/a",
    ]
    assert (result.summary, result.status) == ("✔ All 1 clean", 0)


def test_a_package_packagist_is_up_to_date_on_is_left_alone(projects, packagist, fakes, repo_fix):
    projects.package("a")
    packagist.has("me/a")
    result = repo_fix("--packagist")
    assert (result.progress, result.summary) == ([], "✔ All 1 clean")
    assert fakes.calls("packagist") == []


def test_packagist_is_checked_after_pushing_and_releasing_so_it_is_compared_with_what_was_released(
    projects, packagist, fakes, repo_fix
):
    a = projects.package("a")
    projects.commit(a, "local")
    result = repo_fix("--packagist")
    assert result.progress[:3] == [
        "a",
        "  ✔ Pushed main to origin",
        "  … Running `github release patch`",
    ]
    assert result.progress[6:8] == [
        "  … Running `packagist publish`",
        "  ✔ Published on Packagist:",
    ]


def test_a_failed_packagist_publish_is_reported_and_no_update_is_tried(projects, fakes, repo_fix):
    a = projects.package("a")
    fakes.packagist(REFUSES)
    result = repo_fix("--packagist")
    assert result.progress == [
        "a",
        "  … Running `packagist publish`",
        "  ✘ Packagist publish failed:",
        "    ⚠️ Not today.",
    ]
    assert [call[1:] for call in fakes.calls("packagist")] == [["publish", str(a)]]
    assert (result.listing, result.status) == (["🏠 ❔    🐘 a  main  ✘ 🐘 not on Packagist"], 1)


def test_without_the_packagist_flag_packagist_is_left_alone(projects, fakes, repo_fix):
    projects.package("a")
    result = repo_fix()
    assert (result.progress, result.summary) == ([], "✔ All 1 clean")
    assert fakes.calls("packagist") == []


# --- npm


def test_a_package_not_on_npm_is_published_there_and_waited_for(projects, fakes, repo_fix):
    a = projects.npm_package("a", {"name": "@me/a"})
    result = repo_fix("--npm")
    assert result.progress == [
        "a",
        "  … Running `npmjs publish`, which asks here for npm's one-time passwords",
        "  ✔ Published on npm",
        "  … Running `npmjs wait`, which waits until npm has every version tag",
    ]
    assert [call[1:] for call in fakes.calls("npmjs")] == [
        ["publish", str(a)],
        ["wait", str(a)],
    ]
    assert (result.summary, result.status) == ("✔ All 1 clean", 0)


def test_the_version_tags_npm_lacks_are_waited_for(projects, npm, fakes, repo_fix):
    a = projects.npm_package("a", {"name": "@me/a"})
    npm.has("@me/a", lacking=["v0.2.0"])
    result = repo_fix("--npm")
    assert result.progress == [
        "a",
        "  … Running `npmjs wait`, which waits until npm has every version tag",
        "  ✔ npm published v0.2.0:",
        "    https://www.npmjs.com/package/@me/a",
    ]
    assert [call[1:] for call in fakes.calls("npmjs")] == [["wait", str(a)]]
    assert (result.summary, result.status) == ("✔ All 1 clean", 0)


def test_a_package_npm_is_up_to_date_on_is_left_alone(projects, npm, fakes, repo_fix):
    projects.npm_package("a", {"name": "@me/a"})
    npm.has("@me/a", lacking=[])
    result = repo_fix("--npm")
    assert (result.progress, result.summary) == ([], "✔ All 1 clean")
    assert fakes.calls("npmjs") == []


def test_a_failed_npm_publish_is_reported_and_nothing_is_waited_for(projects, fakes, repo_fix):
    a = projects.npm_package("a", {"name": "@me/a"})
    fakes.npmjs(REFUSES)
    result = repo_fix("--npm")
    assert result.progress == [
        "a",
        "  … Running `npmjs publish`, which asks here for npm's one-time passwords",
        "  ✘ npm publish failed",
    ]
    assert [call[1:] for call in fakes.calls("npmjs")] == [["publish", str(a)]]
    assert (result.listing, result.status) == (["🏠 ❔    🔴 a  main  ✘ 🔴 not on npm"], 1)


def test_a_failed_wait_is_reported_with_what_npmjs_said(projects, npm, fakes, repo_fix):
    projects.npm_package("a", {"name": "@me/a"})
    npm.has("@me/a", lacking=["v0.2.0"])
    fakes.npmjs(REFUSES)
    result = repo_fix("--npm")
    assert result.progress == [
        "a",
        "  … Running `npmjs wait`, which waits until npm has every version tag",
        "  ✘ npm wait failed:",
        "    ⚠️ Not today.",
    ]


def test_without_the_npm_flag_npm_is_left_alone(projects, fakes, repo_fix):
    projects.npm_package("a", {"name": "@me/a"})
    result = repo_fix()
    assert (result.progress, result.summary) == ([], "✔ All 1 clean")
    assert fakes.calls("npmjs") == []


# --- Locked dependencies


def source(projects, name: str) -> Path:
    """A clone of a bare repository outside the root, which a uv.lock can lock as a git source,
    with one commit pushed."""
    clone = projects.remotes.parent / f"{name}-clone"
    projects.git("init", "--quiet", "--bare", projects.remotes / f"{name}.git")
    projects.git("init", "--quiet", clone)
    projects.commit(clone, "init")
    projects.git("-C", clone, "push", "--quiet", projects.remotes / f"{name}.git", "main")
    return clone


def release(projects, name: str) -> None:
    """Pushes a new commit to the source made by source(projects, name)."""
    clone = projects.remotes.parent / f"{name}-clone"
    projects.commit(clone, "release")
    projects.git("-C", clone, "push", "--quiet", projects.remotes / f"{name}.git", "main")


def locking(projects, repo: Path, **sources: Path) -> None:
    """Gives repo a devbox.json, and a uv.lock that locks each source at its HEAD, as the fake uv
    reads it, committed and pushed."""
    at = {name: git(origin, "rev-parse", "--short", "HEAD") for name, origin in sources.items()}
    lock_file = {"sources": {name: str(origin) for name, origin in sources.items()}, "at": at}
    (repo / "uv.lock").write_text(json.dumps(lock_file))
    (repo / "devbox.json").write_text("{}\n")
    git(repo, "add", "uv.lock", "devbox.json")
    git(repo, "commit", "--quiet", "--message", "Lock")
    git(repo, "push", "--quiet")


def test_a_uv_lock_on_the_trunk_that_can_be_upgraded_is_upgraded_committed_and_pushed(
    projects, repo_fix
):
    a = projects.pushed_repo("a")
    dep = source(projects, "dep")
    locking(projects, a, dep=projects.remotes / "dep.git")
    old = git(dep, "rev-parse", "--short", "HEAD")
    release(projects, "dep")
    new = git(dep, "rev-parse", "--short", "HEAD")
    result = repo_fix()
    assert result.progress[:2] == ["a", "  … Running `uv lock --upgrade`"]
    assert re.fullmatch(r"  ✔ Committed \w+ Upgrade the locked dependencies:", result.progress[2])
    assert result.progress[3:] == [f"    Update dep {old} -> {new}", "  ✔ Pushed main to origin"]
    assert git(a, "log", "-1", "--format=%B", "origin/main") == (
        f"Upgrade the locked dependencies\n\nUpdate dep {old} -> {new}"
    )
    assert (result.summary, result.status) == ("✔ All 1 clean", 0)


def test_a_uv_lock_that_cannot_be_upgraded_is_left_alone(projects, fakes, repo_fix):
    a = projects.pushed_repo("a")
    source(projects, "dep")
    locking(projects, a, dep=projects.remotes / "dep.git")
    result = repo_fix()
    assert (result.progress, result.summary) == ([], "✔ All 1 clean")
    assert all("--dry-run" in call for call in fakes.calls("devbox"))


def test_a_uv_lock_that_can_be_upgraded_is_reported_by_how_many_upgrades(projects, fakes, repo_fix):
    a = projects.pushed_repo("a")
    locking(projects, a)
    fakes.devbox(
        """case "$*" in *--dry-run*) printf 'Update one a -> b\\nAdd two v1\\n' >&2 ;; """
        """*) echo 'error: no network' >&2; exit 2 ;; esac"""
    )
    assert any("📌 2 upgrades for uv.lock" in line for line in repo_fix().listing)


def test_only_the_trunk_has_its_uv_lock_upgraded_not_other_worktrees(projects, fakes, repo_fix):
    a = projects.pushed_repo("a")
    source(projects, "dep")
    locking(projects, a, dep=projects.remotes / "dep.git")
    projects.worktree(a, "0-branch", "-b", "feature")
    projects.worktree(a, "0-detached", "--detach")
    release(projects, "dep")
    repo_fix()
    assert {call[0] for call in fakes.calls("devbox")} == {str(a)}
    assert subjects(a, "--all").count("Upgrade the locked dependencies") == 1


def test_with_pr_integration_no_uv_lock_is_upgraded(projects, fakes, repo_fix):
    projects.integration("pr-rebase")
    a = projects.pushed_repo("a")
    source(projects, "dep")
    locking(projects, a, dep=projects.remotes / "dep.git")
    release(projects, "dep")
    result = repo_fix()
    assert (result.progress, fakes.calls("devbox")) == ([], [])


def test_a_failed_upgrade_is_reported_with_what_uv_said_and_nothing_is_committed(
    projects, fakes, repo_fix
):
    a = projects.pushed_repo("a")
    locking(projects, a)
    fakes.devbox(
        """case "$*" in *--dry-run*) echo 'Update dep a -> b' >&2 ;; """
        """*) echo 'error: no network' >&2; exit 2 ;; esac"""
    )
    result = repo_fix()
    assert result.progress == [
        "a",
        "  … Running `uv lock --upgrade`",
        "  ✘ uv lock --upgrade failed:",
        "    error: no network",
    ]
    assert subjects(a)[-1] == "Lock"


def test_a_uv_lock_whose_check_fails_is_reported_and_left_alone(projects, fakes, repo_fix):
    a = projects.pushed_repo("a")
    locking(projects, a)
    fakes.devbox("""echo 'error: no network' >&2; exit 2""")
    result = repo_fix()
    assert result.progress == []
    assert any("📌 uv.lock check failed" in line for line in result.listing)
    assert result.status == 1


def test_a_uv_lock_without_a_devbox_to_run_uv_in_is_reported(projects, fakes, repo_fix):
    a = projects.pushed_repo("a")
    locking(projects, a)
    git(a, "rm", "--quiet", "devbox.json")
    git(a, "commit", "--quiet", "--message", "No devbox")
    git(a, "push", "--quiet")
    result = repo_fix()
    assert (result.progress, fakes.calls("devbox")) == ([], [])
    assert any("📌 no devbox.json to run uv in" in line for line in result.listing)


def test_a_dependant_is_checked_again_once_a_repository_it_pins_is_fixed(projects, repo_fix):
    kit = projects.python_project("kit", python_project("kit"))
    a = projects.python_project("a", python_project("a", "kit"))
    locking(projects, a, kit=projects.origin(kit))
    projects.commit(kit, "local")
    result = repo_fix()
    assert result.progress[:4] == [
        "kit",
        "  ✔ Pushed main to origin",
        "a",
        "  … Running `uv lock --upgrade`",
    ]


# --- Releasing


def released_package(projects, packagist, name: str) -> Path:
    """A package of your vendor's that Packagist is up to date on, released as v1.0.0, with a
    commit since that's on no remote yet."""
    repo = projects.package(name)
    packagist.has(f"me/{name}")
    projects.commit(repo, "work")
    return repo


def test_a_package_with_commits_since_its_latest_version_is_released_as_the_next_patch_once_pushed(
    projects, packagist, fakes, repo_fix
):
    a = released_package(projects, packagist, "a")
    result = repo_fix("--packagist")
    assert result.progress == [
        "a",
        "  ✔ Pushed main to origin",
        "  … Running `github release patch`",
        "  ✔ Released:",
        "    Tagged HEAD as v1.0.1",
        "    Pushed v1.0.1",
    ]
    assert [call[1:] for call in fakes.calls("github")] == [["release", str(a), "patch"]]
    assert "refs/tags/v1.0.1" in git(a, "ls-remote", "--tags", "origin")
    assert (result.summary, result.status) == ("✔ All 1 clean", 0)


def test_the_packages_flag_releases_packages_of_every_kind(projects, npm, fakes, repo_fix):
    a = projects.npm_package("a", {"name": "@me/a"})
    npm.has("@me/a", lacking=[])
    projects.commit(a, "work")
    repo_fix("--packages")
    assert [call[1:] for call in fakes.calls("github")] == [["release", str(a), "patch"]]


def test_commits_that_change_lock_files_alone_are_not_released(
    projects, packagist, fakes, repo_fix
):
    a = projects.package("a")
    packagist.has("me/a")
    (a / "composer.lock").write_text("{}\n")
    git(a, "add", "composer.lock")
    git(a, "commit", "--quiet", "--message", "Lock")
    result = repo_fix("--packagist")
    assert result.progress == ["a", "  ✔ Pushed main to origin"]
    assert fakes.calls("github") == []


def test_a_package_never_released_is_released_as_its_first_version(
    projects, packagist, fakes, repo_fix
):
    a = projects.package("a")
    projects.untag(a, "v1.0.0")
    packagist.has("me/a")
    result = repo_fix("--packagist")
    assert result.progress[:3] == ["a", "  … Running `github release patch`", "  ✔ Released:"]
    assert [call[1:] for call in fakes.calls("github")] == [["release", str(a), "patch"]]


def test_a_package_new_to_npm_is_released_before_it_is_published_there(projects, fakes, repo_fix):
    a = projects.npm_package("a", {"name": "@me/a"})
    projects.untag(a, "v1.0.0")
    result = repo_fix("--npm")
    assert result.progress == [
        "a",
        "  … Running `github release patch`",
        "  ✔ Released:",
        "    Tagged HEAD as v1.0.1",
        "    Pushed v1.0.1",
        "  … Running `npmjs publish`, which asks here for npm's one-time passwords",
        "  ✔ Published on npm",
        "  … Running `npmjs wait`, which waits until npm has every version tag",
    ]


def test_without_a_package_flag_nothing_is_released(projects, packagist, fakes, repo_fix):
    released_package(projects, packagist, "a")
    result = repo_fix()
    assert result.progress == ["a", "  ✔ Pushed main to origin"]
    assert fakes.calls("github") == []


def test_with_pr_integration_nothing_is_released(projects, packagist, fakes, repo_fix):
    projects.integration("pr-rebase")
    a = projects.package("a")
    packagist.has("me/a")
    projects.push_from_elsewhere(a)
    repo_fix("--packagist")
    assert fakes.calls("github") == []


def test_a_failed_release_is_reported_with_what_it_said_and_the_registry_is_not_told(
    projects, packagist, fakes, repo_fix
):
    released_package(projects, packagist, "a")
    packagist.has("me/a", lacking=["main"])
    fakes.github(REFUSES)
    result = repo_fix("--packagist")
    assert result.progress == [
        "a",
        "  ✔ Pushed main to origin",
        "  … Running `github release patch`",
        "  ✘ Release failed:",
        "    ⚠️ Not today.",
    ]
    assert fakes.calls("packagist") == []
    assert any("🔖 1 commit since v1.0.0" in line for line in result.listing)


# --- Upgrading dependants

# The fake composer locks every package at v1.0.1.
COMPOSER_UPDATE = """python3 - <<'EOF'
import json
lock = json.load(open("composer.lock"))
for package in lock["packages"]:
    package["version"] = "v1.0.1"
json.dump(lock, open("composer.lock", "w"))
EOF"""


def composer_app(projects, name: str, kit_at: str) -> Path:
    """A pushed Composer project, with a devbox.json, that requires me/kit and locks it at
    kit_at."""
    repo = projects.pushed_repo(name)
    manifest = {"name": f"me/{name}", "type": "project", "require": {"me/kit": "^1.0"}}
    (repo / "composer.json").write_text(json.dumps(manifest))
    lock_file = {"packages": [{"name": "me/kit", "version": kit_at}]}
    (repo / "composer.lock").write_text(json.dumps(lock_file))
    (repo / "devbox.json").write_text("{}\n")
    git(repo, "add", "--all")
    git(repo, "commit", "--quiet", "--message", "Require me/kit")
    git(repo, "push", "--quiet")
    return repo


def test_a_package_just_released_is_upgraded_in_the_lock_files_of_the_projects_that_pin_it(
    projects, packagist, fakes, repo_fix
):
    released_package(projects, packagist, "kit")
    app = composer_app(projects, "app", "v1.0.0")
    fakes.devbox(COMPOSER_UPDATE)
    result = repo_fix("--packagist")
    assert result.progress[:6] == [
        "kit",
        "  ✔ Pushed main to origin",
        "  … Running `github release patch`",
        "  ✔ Released:",
        "    Tagged HEAD as v1.0.1",
        "    Pushed v1.0.1",
    ]
    assert result.progress[6:8] == [
        "app",
        "  … Running `composer update --no-interaction --no-install --no-scripts me/kit`",
    ]
    assert re.fullmatch(r"  ✔ Committed \w+ Upgrade me/kit:", result.progress[8])
    assert result.progress[9:] == ["    me/kit v1.0.0 -> v1.0.1", "  ✔ Pushed main to origin"]
    assert git(app, "log", "-1", "--format=%B", "origin/main") == (
        "Upgrade me/kit\n\nme/kit v1.0.0 -> v1.0.1"
    )
    assert git(app, "show", "--name-only", "--format=", "HEAD") == "composer.lock"
    assert (result.summary, result.status) == ("✔ All 2 clean", 0)


def test_a_library_s_upgrade_of_a_package_of_yours_is_not_itself_released(
    projects, packagist, fakes, repo_fix
):
    kit = projects.package("kit")
    packagist.has("me/kit")
    projects.tag(kit, "v1.0.1")
    lib = composer_app(projects, "lib", "v1.0.0")
    (lib / "composer.json").write_text(json.dumps({"name": "me/lib", "require": {"me/kit": "^1"}}))
    git(lib, "commit", "--quiet", "--all", "--message", "A library")
    git(lib, "push", "--quiet")
    projects.tag(lib, "v1.0.0")
    packagist.has("me/lib")
    fakes.devbox(COMPOSER_UPDATE)
    repo_fix("--packagist")
    assert subjects(lib)[-1] == "Upgrade me/kit"
    assert fakes.calls("github") == []


def test_a_lock_file_its_tool_leaves_as_it_was_is_reported_and_nothing_is_committed(
    projects, packagist, fakes, repo_fix
):
    kit = projects.package("kit")
    packagist.has("me/kit")
    projects.tag(kit, "v1.0.1")
    app = composer_app(projects, "app", "v1.0.0")
    fakes.devbox("true")
    result = repo_fix("--packagist")
    assert result.progress == [
        "app",
        "  … Running `composer update --no-interaction --no-install --no-scripts me/kit`",
        "  ✘ composer left composer.lock as it was; its constraint may exclude the latest:",
        "    me/kit v1.0.0 -> v1.0.1",
    ]
    assert subjects(app)[-1] == "Require me/kit"
    assert any("🔗 composer.lock behind on me/kit" in line for line in result.listing)


def test_a_lock_file_without_a_devbox_to_upgrade_it_in_is_reported(
    projects, packagist, fakes, repo_fix
):
    kit = projects.package("kit")
    packagist.has("me/kit")
    projects.tag(kit, "v1.0.1")
    app = composer_app(projects, "app", "v1.0.0")
    git(app, "rm", "--quiet", "devbox.json")
    git(app, "commit", "--quiet", "--message", "No devbox")
    git(app, "push", "--quiet")
    result = repo_fix("--packagist")
    assert result.progress == [
        "app",
        "  ✘ Not upgrading composer.lock: there's no devbox.json to run composer in",
    ]
    assert fakes.calls("devbox") == []


def test_a_lock_file_holding_the_latest_of_your_packages_is_left_alone(
    projects, packagist, fakes, repo_fix
):
    kit = projects.package("kit")
    packagist.has("me/kit")
    projects.tag(kit, "v1.0.1")
    composer_app(projects, "app", "v1.0.1")
    result = repo_fix("--packagist")
    assert (result.progress, fakes.calls("devbox")) == ([], [])


def test_without_a_package_flag_no_lock_file_is_upgraded_to_your_packages(
    projects, packagist, fakes, repo_fix
):
    kit = projects.package("kit")
    projects.tag(kit, "v1.0.1")
    composer_app(projects, "app", "v1.0.0")
    result = repo_fix()
    assert (result.progress, fakes.calls("devbox")) == ([], [])


# The fake uv locks kit at the commit its origin's main is at, and finds nothing else to upgrade.
UV_UPGRADE_PACKAGE = """case "$*" in *--upgrade-package*) python3 - <<'EOF'
import os, re, subprocess
origin = os.environ["KIT_ORIGIN"]
head = subprocess.run(
    ["git", "--git-dir", origin, "rev-parse", "main"], capture_output=True, text=True, check=True
).stdout.strip()
text = open("uv.lock").read()
open("uv.lock", "w").write(re.sub(r"#\\w+", "#" + head, text))
EOF
;; esac"""


def test_a_python_package_pushed_is_upgraded_to_its_trunk_in_the_uv_locks_that_pin_it(
    projects, fakes, repo_fix, monkeypatch
):
    kit = projects.python_project("kit", python_project("kit"))
    app = projects.python_project("app", python_project("app", "kit"))
    old = git(kit, "rev-parse", "HEAD")
    url = "https://example.com/kit?branch=main#" + old
    (app / "uv.lock").write_text(
        f'version = 1\n\n[[package]]\nname = "kit"\nsource = {{ git = "{url}" }}\n'
    )
    (app / "devbox.json").write_text("{}\n")
    git(app, "add", "--all")
    git(app, "commit", "--quiet", "--message", "Lock")
    git(app, "push", "--quiet")
    projects.commit(kit, "work")
    new = git(kit, "rev-parse", "HEAD")
    monkeypatch.setenv("KIT_ORIGIN", str(projects.origin(kit)))
    fakes.devbox(UV_UPGRADE_PACKAGE)
    result = repo_fix("--python")
    assert result.progress[:4] == [
        "kit",
        "  ✔ Pushed main to origin",
        "app",
        "  … Running `uv lock --upgrade-package kit`",
    ]
    assert re.fullmatch(r"  ✔ Committed \w+ Upgrade kit:", result.progress[4])
    assert result.progress[5:] == [f"    kit {old[:7]} -> {new[:7]}", "  ✔ Pushed main to origin"]
    assert fakes.calls("github") == []
    assert (result.summary, result.status) == ("✔ All 2 clean", 0)


# The fake go get requires every module at v1.0.1, and records its checksum in a new go.sum.
GO_GET = """python3 - <<'EOF'
text = open("go.mod").read()
open("go.mod", "w").write(text.replace(" v1.0.0", " v1.0.1"))
open("go.sum", "w").write("github.com/me/kit v1.0.1 h1:sum=\\n")
EOF"""


def go_module(projects, name: str, go_mod: str) -> Path:
    """A pushed repository with a devbox.json, whose go.mod is module github.com/me/name followed
    by go_mod."""
    repo = projects.pushed_repo(name)
    (repo / "go.mod").write_text(f"module github.com/me/{name}\n\ngo 1.27\n{go_mod}")
    (repo / "devbox.json").write_text("{}\n")
    git(repo, "add", "--all")
    git(repo, "commit", "--quiet", "--message", "go.mod")
    git(repo, "push", "--quiet")
    return repo


def test_a_go_module_another_requires_is_released_then_upgraded_in_its_go_mod_and_go_sum(
    projects, fakes, repo_fix
):
    kit = go_module(projects, "kit", "")
    projects.tag(kit, "v1.0.0")
    projects.commit(kit, "work")
    app = go_module(projects, "app", "\nrequire github.com/me/kit v1.0.0\n")
    fakes.devbox(GO_GET)
    result = repo_fix("--go")
    assert result.progress[:6] == [
        "kit",
        "  ✔ Pushed main to origin",
        "  … Running `github release patch`",
        "  ✔ Released:",
        "    Tagged HEAD as v1.0.1",
        "    Pushed v1.0.1",
    ]
    assert result.progress[6:8] == [
        "app",
        "  … Running `env GOPROXY=direct go get github.com/me/kit@latest`",
    ]
    assert re.fullmatch(r"  ✔ Committed \w+ Upgrade github.com/me/kit:", result.progress[8])
    assert result.progress[9:] == [
        "    github.com/me/kit v1.0.0 -> v1.0.1",
        "  ✔ Pushed main to origin",
    ]
    assert git(app, "show", "--name-only", "--format=", "origin/main").splitlines() == [
        "go.mod",
        "go.sum",
    ]
    assert (result.summary, result.status) == ("✔ All 2 clean", 0)


# --- Directories that are not repositories


def test_a_directory_of_files_is_left_alone_by_default(projects, fakes, repo_fix):
    (projects.root / "notes").mkdir()
    (projects.root / "notes" / "todo").write_text("x\n")
    result = repo_fix()
    assert result.progress == []
    assert result.listing == ["notes  ✘ 📁 not a git repository"]
    assert fakes.calls("claude") == fakes.calls("github") == []


def test_the_init_flag_makes_a_directory_of_files_a_published_repository(projects, fakes, repo_fix):
    notes = projects.root / "notes"
    notes.mkdir()
    (notes / "todo").write_text("x\n")
    result = repo_fix("--init")
    assert result.progress[:2] == ["notes", "  ✔ Initialised a git repository"]
    assert subjects(fakes.remote) == ["Fake commit"]
    assert result.listing == [
        "🔧 ❔    notes  main  ✘ 🔧 Set `integration` in .config/ianf-repo-tools.toml"
    ]


# --- What it leaves alone


def test_stashes_and_commits_on_a_detached_head_are_left_for_you(projects, fakes, repo_fix):
    a = projects.pushed_repo("a")
    (a / "f").write_text("change\n")
    git(a, "stash", "--quiet")
    git(a, "checkout", "--quiet", "--detach")
    projects.commit(a, "lost")
    result = repo_fix()
    assert result.progress == []
    assert result.listing == [
        f"🏠 ❔    a  @{projects.short_head(a)}  ✘ 👻 1 commit on detached HEAD  📦 1 stash"
    ]
    assert result.status == 1


def test_a_clean_repository_has_nothing_done_to_it(projects, fakes, repo_fix):
    projects.pushed_repo("a")
    result = repo_fix()
    assert (result.progress, result.summary, result.status) == ([], "✔ All 1 clean", 0)
    assert fakes.calls("claude") == fakes.calls("github") == []


# --- Which repositories


def test_a_path_to_a_repository_fixes_only_that_repository(projects, repo_fix):
    a = projects.pushed_repo("a")
    b = projects.pushed_repo("b")
    projects.commit(a, "local")
    projects.commit(b, "local")
    result = repo_fix(b)
    assert result.progress == ["b", "  ✔ Pushed main to origin"]
    assert result.summary == "✔ All 1 clean"
    assert subjects(projects.origin(a)) == ["init"]


def test_a_path_to_a_directory_fixes_every_repository_under_it(projects, repo_fix):
    (projects.root / "group").mkdir()
    a = projects.pushed_repo("group/a")
    b = projects.pushed_repo("group/b")
    projects.commit(a, "local")
    projects.commit(b, "local")
    result = repo_fix(projects.root / "group")
    assert result.progress == ["a", "  ✔ Pushed main to origin", "b", "  ✔ Pushed main to origin"]
    assert result.summary == "✔ All 2 clean"


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
    assert result.summary == "✔ All 2 clean"


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
        "  \x1b[38;5;246m… Committing with Claude Code's /ianf-commit, which can take a few minutes"
        "\x1b[0m",
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
        "  … Committing with Claude Code's /ianf-commit, which can take a few minutes",
        f"  ✔ Committed {git(a, 'rev-parse', '--short', 'HEAD')} Fake commit",
        "  ✘ Commit left work uncommitted:",
        "    Kept g out.",
    ]
