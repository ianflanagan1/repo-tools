"""📤 Commits on no remote, pushed; 📥 commits on the upstream a branch lacks, fast-forwarded.

Nothing is forced: a branch both behind and unpushed has diverged, and is left alone. Nothing is
pushed or pulled in a repository whose fetch failed, as what's on its remotes isn't known.
"""

import re
from dataclasses import dataclass

from repo_list.git import git, run
from repo_list.plugin import Log, Plugin, Problem, Stage
from repo_list.scan import Folder


@dataclass(frozen=True)
class Unpushed:
    """Commits on a local branch that are on no remote."""

    branch: str
    commits: int

    def describe(self) -> str:
        return f"📤 {self.commits} unpushed on {self.branch}"


@dataclass(frozen=True)
class Behind:
    """Commits on the branch's upstream that it lacks, as of the last fetch."""

    branch: str
    commits: int

    def describe(self) -> str:
        return f"📥 {self.commits} behind on {self.branch}"


class Sync(Plugin):
    name = "sync"
    stage = Stage.SYNC

    def check(self, folder: Folder) -> list[Problem]:
        repo = folder.path
        problems: list[Problem] = []
        has_remote = bool(git(repo, "remote"))
        branches = git(
            repo,
            "for-each-ref",
            "--format=%(refname:short)\t%(upstream:track,nobracket)",
            "refs/heads",
        )
        for line in branches.splitlines():
            branch, _, track = line.partition("\t")
            # Count commits on no remote, rather than ahead of the upstream, so that a branch
            # without an upstream is still checked. With no remote, the github plugin's
            # "no remote" already says it all.
            if has_remote:
                unpushed = int(
                    git(repo, "rev-list", "--count", f"refs/heads/{branch}", "--not", "--remotes")
                )
                if unpushed:
                    problems.append(Unpushed(branch, unpushed))
            # track is like "ahead 1, behind 2", as of the last fetch.
            if behind := re.search(r"behind (\d+)", track):
                problems.append(Behind(branch, int(behind[1])))
        return problems

    def fix(self, folder: Folder, problems: list[Problem], log: Log) -> bool:
        if folder.fetch_failed:
            return True
        repo = folder.path
        behind = {p.branch for p in problems if isinstance(p, Behind)}
        unpushed = {p.branch for p in problems if isinstance(p, Unpushed)}
        for branch in sorted(behind | unpushed):
            upstream = git(repo, "rev-parse", "--abbrev-ref", f"{branch}@{{u}}", check=False)
            if branch in behind and branch in unpushed:
                log(False, f"Not syncing {branch}: it has diverged from {upstream}")
            elif branch in behind:
                fast_forward(folder, branch, upstream, log)
            else:
                push(folder, branch, upstream, log)
        return True


def fast_forward(folder: Folder, branch: str, upstream: str, log: Log) -> None:
    repo = folder.path
    current = git(repo, "symbolic-ref", "-q", "--short", "HEAD", check=False)
    if branch == current:
        command = ["merge", "-q", "--ff-only", upstream]
    else:
        command = ["fetch", "-q", ".", f"refs/remotes/{upstream}:refs/heads/{branch}"]
    result = run(repo, *command)
    if result.returncode == 0:
        log(True, f"Fast-forwarded {branch} to {upstream}")
    else:
        log(False, f"Fast-forward of {branch} failed", *result.stderr.strip().splitlines())


def push(folder: Folder, branch: str, upstream: str, log: Log) -> None:
    repo = folder.path
    if upstream:
        remote = git(repo, "config", f"branch.{branch}.remote")
        merge = git(repo, "config", f"branch.{branch}.merge")
        result = run(repo, "push", "-q", remote, f"refs/heads/{branch}:{merge}")
        done = f"Pushed {branch} to {remote}"
    else:
        remotes = git(repo, "remote").splitlines()
        if len(remotes) != 1:
            choices = f"{len(remotes)} remotes to choose from"
            log(False, f"Not pushing {branch}: it has no upstream, and {choices}")
            return
        result = run(repo, "push", "-q", "-u", remotes[0], branch)
        done = f"Pushed {branch} to {remotes[0]}, now its upstream"
    if result.returncode == 0:
        log(True, done)
    else:
        log(False, f"Push of {branch} failed", *result.stderr.strip().splitlines())
