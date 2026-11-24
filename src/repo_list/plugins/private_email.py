"""📧 A private email that pushing would publish: git committing as one here, or a commit on no
remote yet showing one as its author or committer. Which emails are private is config.toml's
email.private; none are until it names some.

repo-fix rewrites the commits on no remote of the branch checked out that show one, to show the
author git commits as now, keeping their author dates; the rest are rewritten only as their
parents change, which leaves their authors as they were. Nothing pushed is ever rewritten. Where
git itself commits as a private email, a branch not checked out shows one, or the commits to
rewrite include a merge, it's left for you, and nothing more is done in the directory, so nothing
there is pushed or published. A repository kept on this computer only isn't checked: it's checked
when it's published, as every commit is then on no remote.
"""

import re
import shlex
from dataclasses import dataclass
from pathlib import Path

from repo_list.git import git, in_progress, run
from repo_list.git_hosts import LocalOnly
from repo_list.integration import branches_to_check
from repo_list.plugin import Log, Plugin, Problem, Stage, count
from repo_list.scan import Directory


@dataclass(frozen=True)
class CommitsAsPrivate:
    """Git commits here as a private email, as its author or committer."""

    def describe(self) -> str:
        return "📧 git commits here as a private email"


@dataclass(frozen=True)
class ShowsPrivate:
    branch: str
    commits: int

    def describe(self) -> str:
        verb = "shows" if self.commits == 1 else "show"
        return f"📧 {count(self.commits, 'commit')} on {self.branch} {verb} a private email"


class PrivateEmail(Plugin):
    name = "private-email"
    stage = Stage.BEFORE_PUSH

    def __init__(self, private: tuple[str, ...]) -> None:
        """private: the private emails, in lower case."""
        self.private = private

    def check(self, directory: Directory) -> list[Problem]:
        place = directory.place
        if place is None or isinstance(place.origin, LocalOnly):
            return []
        repo = directory.path
        problems: list[Problem] = []
        if any(email in self.private for email in identities(repo)):
            problems.append(CommitsAsPrivate())
        branches = git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads")
        for branch in branches_to_check(
            place.head, place.is_main, branches.splitlines(), place.worktrees, place.trunk
        ):
            shown = len(self._showing(repo, branch))
            if shown:
                problems.append(ShowsPrivate(branch, shown))
        return problems

    def fix(self, directory: Directory, problems: list[Problem], log: Log) -> bool:
        """Rewrites the commits on the branch checked out that show a private email. Says whether
        none is left to push."""
        if directory.fetch_failed or directory.place is None:
            return True
        repo = directory.path
        if any(isinstance(p, CommitsAsPrivate) for p in problems):
            log(
                False,
                "Not pushing: git commits here as a private email; set user.email for this"
                " git host",
            )
            return False
        head = directory.place.head
        for problem in problems:
            if isinstance(problem, ShowsPrivate) and problem.branch != head:
                log(
                    False,
                    f"Not pushing: {problem.branch} has commits showing a private email; check it"
                    " out and run repo-fix there",
                )
                return False
        if head is None or not any(isinstance(p, ShowsPrivate) for p in problems):
            return True
        return self._rewrite(repo, head, log)

    def _rewrite(self, repo: Path, branch: str, log: Log) -> bool:
        if operation := in_progress(repo):
            log(False, f"Not rewriting {branch}: {operation} is in progress")
            return False
        if git(repo, "status", "--porcelain"):
            log(False, f"Not rewriting {branch}: it has uncommitted work")
            return False
        unpushed = [f"refs/heads/{branch}", "--not", "--remotes"]
        if int(git(repo, "rev-list", "--count", "--merges", *unpushed)):
            log(
                False,
                f"Not pushing: {branch} has commits showing a private email among merges;"
                " rewrite them yourself",
            )
            return False

        showing = self._showing(repo, branch)
        oldest = showing[-1]
        parent = git(repo, "rev-parse", "--quiet", "--verify", f"{oldest}^", check=False)
        name, email = identity(repo, "GIT_AUTHOR_IDENT")
        # Each commit picked is made again with the committer git commits as now; the exec then
        # gives a commit that shows a private email the author too, keeping its author date.
        matches = " ".join(f"-e {shlex.quote(e)}" for e in self.private)
        amend = shlex.join(
            [
                "git",
                "commit",
                "--quiet",
                "--amend",
                "--no-edit",
                "--allow-empty",
                f"--author={name} <{email}>",
            ]
        )
        command = (
            "if git log -1 --format='%ae%n%ce' | tr '[:upper:]' '[:lower:]'"
            f" | grep -qxF {matches}; then {amend}; fi"
        )
        onto = [parent] if parent else ["--root"]
        rebased = run(repo, "rebase", "--quiet", "--exec", command, *onto)
        if rebased.returncode != 0:
            run(repo, "rebase", "--abort")
            log(False, f"Rewriting {branch} failed:", *rebased.stderr.splitlines())
            return False
        if self._showing(repo, branch):
            log(False, f"Rewriting {branch} left commits showing a private email")
            return False
        log(True, f"Rewrote {count(len(showing), 'commit')} on {branch} to show {email}")
        return True

    def _showing(self, repo: Path, branch: str) -> list[str]:
        """The commits on branch and on no remote that show a private email, newest first."""
        lines = git(
            repo, "log", "--format=%H%x09%ae%x09%ce", f"refs/heads/{branch}", "--not", "--remotes"
        )
        return [
            fields[0]
            for fields in (line.split("\t") for line in lines.splitlines())
            if fields[1].lower() in self.private or fields[2].lower() in self.private
        ]


def identities(repo: Path) -> list[str]:
    """The emails, in lower case, git commits as here, as author and committer; none where it
    can't tell, as when user.useConfigOnly is set with no email."""
    found = [identity(repo, ident) for ident in ("GIT_AUTHOR_IDENT", "GIT_COMMITTER_IDENT")]
    return [email.lower() for _, email in found if email]


def identity(repo: Path, ident: str) -> tuple[str, str]:
    """The name and email git var gives for ident, or empty ones where it can't tell."""
    match = re.match(r"^(.*) <(.*)> \d+ [+-]\d{4}$", git(repo, "var", ident, check=False))
    return (match.group(1), match.group(2)) if match else ("", "")
