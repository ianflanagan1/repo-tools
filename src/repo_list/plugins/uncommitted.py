"""📝 Files changed, staged or untracked, committed by Claude Code's /commit skill.

The commit is judged by git's state, not by what Claude says: the work tree must then be clean,
on the same branch, with the earlier commits untouched.
"""

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from repo_list.git import git, run
from repo_list.plugin import Log, Plugin, Problem, Stage, count
from repo_list.scan import Folder

CLAUDE = "claude"
COMMIT_SKILL = "~/.claude/skills/commit"
COMMIT_TIMEOUT_SECONDS = 30 * 60

# The marker git leaves in the git directory during each operation /commit must not interrupt.
IN_PROGRESS = {
    "MERGE_HEAD": "a merge",
    "rebase-merge": "a rebase",
    "rebase-apply": "a rebase",
    "CHERRY_PICK_HEAD": "a cherry-pick",
    "REVERT_HEAD": "a revert",
}


@dataclass(frozen=True)
class UncommittedFiles:
    files: int

    def describe(self) -> str:
        return f"📝 {count(self.files, 'uncommitted file')}"


class Uncommitted(Plugin):
    name = "uncommitted"
    stage = Stage.COMMIT

    def check(self, folder: Folder) -> list[Problem]:
        files = len(git(folder.path, "status", "--porcelain").splitlines())
        return [UncommittedFiles(files)] if files else []

    def fix(self, folder: Folder, problems: list[Problem], log: Log) -> bool:
        """Commits all the work with /commit, and checks the result. Says whether it all went
        in."""
        repo = folder.path
        for marker, operation in IN_PROGRESS.items():
            if (repo / git(repo, "rev-parse", "--git-path", marker)).exists():
                log(False, f"Not committing: {operation} is in progress")
                return False
        branch = git(repo, "symbolic-ref", "-q", "--short", "HEAD", check=False)
        if not branch:
            log(False, "Not committing: HEAD is detached")
            return False
        skill = Path(COMMIT_SKILL).expanduser()
        if not (skill / "SKILL.md").is_file():
            log(False, f"Not committing: no commit skill in {skill}")
            return False

        start = git(repo, "rev-parse", "-q", "--verify", "HEAD", check=False)
        try:
            said = claude_commit(repo, skill)
        except subprocess.TimeoutExpired:
            log(False, f"Commit failed: claude took over {COMMIT_TIMEOUT_SECONDS // 60} minutes")
            return False

        # Judge the run by git's state, not by what claude says: a skill that fails to load
        # still ends as a success, with nothing done.
        now_on = git(repo, "symbolic-ref", "-q", "--short", "HEAD", check=False)
        if now_on != branch:
            log(False, f"Commit failed: it left {branch} for {now_on or 'a detached HEAD'}")
            return False
        head = git(repo, "rev-parse", "-q", "--verify", "HEAD", check=False)
        if start and head != start and not is_ancestor(repo, start, head):
            short = git(repo, "rev-parse", "--short", start)
            log(
                False,
                f"Commit failed: it rewrote commits made before it; the branch was at {short}",
            )
            return False
        if head and head != start:
            revisions = f"{start}..{head}" if start else head
            for line in git(repo, "log", "--reverse", "--format=%h %s", revisions).splitlines():
                log(True, f"Committed {line}")
        if git(repo, "status", "--porcelain"):
            failed = "Commit left work uncommitted" if head != start else "Commit failed"
            log(False, failed, *said.splitlines())
            return False
        return True


def claude_commit(repo: Path, skill: Path) -> str:
    """Runs /commit in repo, headless, and returns what claude said.

    The skill's files may be symlinks to elsewhere, and claude lets the skill read only files
    in its working directories, so every directory they lead to is added.
    """
    allowed = {skill.resolve()} | {
        p.resolve() if p.is_dir() else p.resolve().parent for p in skill.rglob("*")
    }
    result = subprocess.run(
        [
            CLAUDE,
            "-p",
            "/commit",
            *(arg for directory in sorted(allowed) for arg in ("--add-dir", str(directory))),
            "--output-format",
            "json",
            "--no-session-persistence",
        ],
        cwd=repo,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=COMMIT_TIMEOUT_SECONDS,
    )
    try:
        return str(json.loads(result.stdout)["result"])
    except (json.JSONDecodeError, KeyError, TypeError):
        return (result.stdout + result.stderr).strip()


def is_ancestor(repo: Path, older: str, newer: str) -> bool:
    return run(repo, "merge-base", "--is-ancestor", older, newer).returncode == 0
