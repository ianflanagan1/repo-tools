"""📝 Files changed, staged or untracked, committed by Claude Code's /ianf-commit skill.

The commit is judged by git's state, not by what Claude says: the work tree must then be clean,
on the same branch or detached HEAD, with the earlier commits untouched. Where work goes by pull
request nothing is committed on the trunk: it belongs on a branch.
"""

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from repo_list.git import git, in_progress, run
from repo_list.plugin import Log, Plugin, Problem, Stage, count
from repo_list.scan import Directory

CLAUDE = "claude"
COMMIT_SKILL = "ianf-commit"
SKILLS = "~/.claude/skills"
COMMIT_TIMEOUT_SECONDS = 30 * 60


@dataclass(frozen=True)
class UncommittedFiles:
    files: int

    def describe(self) -> str:
        return f"📝 {count(self.files, 'uncommitted file')}"


class Uncommitted(Plugin):
    name = "uncommitted"
    stage = Stage.COMMIT

    def check(self, directory: Directory) -> list[Problem]:
        files = len(git(directory.path, "status", "--porcelain").splitlines())
        return [UncommittedFiles(files)] if files else []

    def fix(self, directory: Directory, problems: list[Problem], log: Log) -> bool:
        """Commits all the work with the commit skill, and checks the result. Says whether it all
        went in."""
        repo = directory.path
        if operation := in_progress(repo):
            log(False, f"Not committing: {operation} is in progress")
            return False
        branch = git(repo, "symbolic-ref", "-q", "--short", "HEAD", check=False)
        place = directory.place
        by_pull_request = place and place.integration and place.integration.by_pull_request
        if by_pull_request and branch and branch == place.trunk:
            log(False, f"Not committing on {branch}: work goes on a branch, for a pull request")
            return False
        skill = Path(SKILLS).expanduser() / COMMIT_SKILL
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
            left, now = branch or "a detached HEAD", now_on or "a detached HEAD"
            log(False, f"Commit failed: it left {left} for {now}")
            return False
        head = git(repo, "rev-parse", "-q", "--verify", "HEAD", check=False)
        if start and head != start and not is_ancestor(repo, start, head):
            short = git(repo, "rev-parse", "--short", start)
            log(
                False,
                f"Commit failed: it rewrote commits made before it; HEAD was at {short}",
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
    """Runs the commit skill in repo, headless, and returns what claude said.

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
            f"/{COMMIT_SKILL}",
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
