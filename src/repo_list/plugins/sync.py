"""How each branch a directory reports on stands against its upstream and the trunk, and bringing
them level, as the repository's integration says (see repo_list.integration):

  📤 commits on no remote, pushed         ⛔ commits on the trunk, where work goes by PR
  📥 behind the upstream, pulled          🛬 commits not landed on the trunk, with local integration
  🔄 HEAD behind its base, caught up      ⚡ HEAD behind its base, conflicting

repo-fix first brings each branch level with its upstream, the trunk first; then catches HEAD up
with its base by rebase, or with pr-merge integration by merge; then pushes. Nothing is forced,
except a branch rebased with pr-rebase integration, which is pushed with a lease. A rebase or merge
that stops at a conflict is undone. Nothing is pushed or pulled in a repository whose fetch
failed, as what's on its remotes isn't known, and nothing is caught up with a trunk that failed to
update.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import assert_never, final

from git_default_branch import remote_to_ask

from repo_list.git import git, in_progress, run
from repo_list.integration import (
    Branch,
    CatchUp,
    Diverged,
    FastForward,
    Head,
    Pull,
    Push,
    RebaseOnUpstream,
    WouldConflict,
    assess_branch,
    assess_head,
    branches_to_check,
    plan_catch_up,
    plan_pulls,
    plan_pushes,
)
from repo_list.plugin import Log, Plugin, Problem, Stage
from repo_list.scan import Directory


@final
@dataclass(frozen=True)
class Facts:
    branches: list[Branch]
    """The branches the directory reports on, the trunk first."""
    upstreams: dict[str, str]
    """Each branch's upstream, such as origin/main, or "" for none."""
    head: Head | None
    """How far HEAD is behind its base, or None when it is the trunk or has none."""
    has_remote: bool


class Sync(Plugin):
    name = "sync"
    stage = Stage.SYNC

    def check(self, directory: Directory) -> list[Problem]:
        if directory.place is None or directory.place.integration is None:
            return []
        integration = directory.place.integration
        facts = gather(directory)
        problems: list[Problem] = [
            problem
            for branch in facts.branches
            for problem in assess_branch(branch, integration, facts.has_remote)
        ]
        if facts.head:
            problems.extend(assess_head(facts.head, integration))
        return problems

    def fix(self, directory: Directory, problems: list[Problem], log: Log) -> bool:
        place = directory.place
        if directory.fetch_failed or place is None or place.integration is None:
            return True
        integration = place.integration
        facts = gather(directory)
        for pull in plan_pulls(facts.branches, integration):
            if not do_pull(directory, pull, facts.upstreams, log) and pull.branch == place.trunk:
                directory.trunk_update_failed = True

        facts = gather(directory)
        if facts.head and (action := plan_catch_up(facts.head, integration)):
            on_local_trunk = facts.head.base == place.trunk
            if on_local_trunk and (directory.trunk_update_failed or directory.trunk_stale):
                log(False, f"Not catching up with {place.trunk}: updating it failed")
            else:
                catch_up(directory, action, log)

        facts = gather(directory)
        for push_ in plan_pushes(facts.branches, integration):
            push(directory, push_, facts.upstreams.get(push_.branch, ""), log)
        return True


def gather(directory: Directory) -> Facts:
    """The facts about the directory's branches and HEAD that its integration goes by."""
    place = directory.place
    repo = directory.path
    if place is None:
        return Facts([], {}, None, False)
    remotes = git(repo, "remote").splitlines()
    refs = git(
        repo,
        "for-each-ref",
        "--format=%(refname:short)\t%(upstream:short)\t%(upstream:track,nobracket)",
        "refs/heads",
    )
    known: dict[str, tuple[str, str]] = {}
    for line in refs.splitlines():
        # The output is stripped, which takes the empty fields off the end of the last line.
        name, upstream, track = (line.split("\t") + ["", ""])[:3]
        known[name] = (upstream, track)

    trunk = place.trunk
    trunk_ref = f"refs/heads/{trunk}" if trunk in known else None
    branches = []
    for name in branches_to_check(place.head, place.is_main, list(known), place.worktrees, trunk):
        upstream, track = known[name]
        # Count commits on no remote, rather than ahead of the upstream, so that a branch
        # without an upstream is still checked.
        unpushed = _count(repo, f"refs/heads/{name}", "--not", "--remotes") if remotes else 0
        # track is like "ahead 1, behind 2", as of the last fetch.
        behind = re.search(r"behind (\d+)", track)
        unmerged = (
            _count(repo, f"{trunk_ref}..refs/heads/{name}") if trunk_ref and name != trunk else 0
        )
        branches.append(
            Branch(
                name,
                here=name == place.head,
                trunk=None if trunk is None else name == trunk,
                has_upstream=bool(upstream),
                unpushed=unpushed,
                behind=int(behind[1]) if behind else 0,
                unmerged=unmerged,
            )
        )
    upstreams = {name: upstream for name, (upstream, _) in known.items()}
    return Facts(branches, upstreams, _head(directory, remotes), bool(remotes))


def _head(directory: Directory, remotes: list[str]) -> Head | None:
    """How far HEAD is behind the branch it lands on: the trunk with local integration, and the
    trunk on the remote where work goes by pull request."""
    place = directory.place
    repo = directory.path
    if place is None or place.trunk is None or place.head == place.trunk:
        return None
    if not git(repo, "rev-parse", "-q", "--verify", "HEAD", check=False):
        return None
    if place.integration is None:
        return None
    if place.integration.by_pull_request:
        remote = remote_to_ask(remotes)
        if remote is None:
            return None
        base = f"{remote}/{place.trunk}"
        ref = f"refs/remotes/{base}"
    else:
        base = place.trunk
        ref = f"refs/heads/{base}"
    if not git(repo, "rev-parse", "-q", "--verify", ref, check=False):
        return None
    behind = _count(repo, f"HEAD..{ref}")
    conflicts = bool(behind) and (
        run(repo, "merge-tree", "--write-tree", "--quiet", ref, "HEAD").returncode == 1
    )
    return Head(place.head, base, behind, conflicts)


def do_pull(directory: Directory, pull: Pull, upstreams: dict[str, str], log: Log) -> bool:
    """Brings a branch level with its upstream. Says whether it now is."""
    upstream = upstreams.get(pull.branch, "")
    match pull:
        case FastForward(branch, here):
            return fast_forward(directory, branch, here, upstream, log)
        case RebaseOnUpstream(branch):
            return rebase_on_upstream(directory, branch, upstream, log)
        case Diverged(branch):
            log(False, f"Not syncing {branch}: it has diverged from {upstream}")
            return False
        case _:
            assert_never(pull)


def fast_forward(directory: Directory, branch: str, here: bool, upstream: str, log: Log) -> bool:
    repo = directory.path
    if here:
        command = ["merge", "-q", "--ff-only", upstream]
    else:
        command = ["fetch", "-q", ".", f"refs/remotes/{upstream}:refs/heads/{branch}"]
    result = run(repo, *command)
    if result.returncode == 0:
        log(True, f"Fast-forwarded {branch} to {upstream}")
        return True
    log(False, f"Fast-forward of {branch} failed", *result.stderr.strip().splitlines())
    return False


def rebase_on_upstream(directory: Directory, branch: str, upstream: str, log: Log) -> bool:
    if reason := _not_clean(directory):
        log(False, f"Not rebasing {branch} onto {upstream}: {reason}")
        return False
    if _replay(directory, ["rebase", "-q", upstream], "rebase", f"{branch} onto {upstream}", log):
        log(True, f"Rebased {branch} onto {upstream}")
        return True
    return False


def catch_up(directory: Directory, action: CatchUp | WouldConflict, log: Log) -> None:
    """Brings the base's commits into HEAD, by rebase or merge, leaving HEAD as it was if that
    stops at a conflict."""
    match action:
        case WouldConflict(base):
            log(False, f"Not catching up with {base}: it would conflict, which is for you")
        case CatchUp(base, rebase=True):
            if reason := _not_clean(directory):
                log(False, f"Not rebasing onto {base}: {reason}")
            elif _replay(directory, ["rebase", "-q", base], "rebase", f"onto {base}", log):
                log(True, f"Rebased onto {base}")
        case CatchUp(base, rebase=False):
            if reason := _not_clean(directory):
                log(False, f"Not merging {base}: {reason}")
            elif _replay(directory, ["merge", "-q", "--no-edit", base], "merge", base, log):
                log(True, f"Merged {base}")
        case _:
            assert_never(action)


def push(directory: Directory, action: Push, upstream: str, log: Log) -> None:
    repo = directory.path
    branch = action.branch
    lease = ["--force-with-lease", "--force-if-includes"] if action.force else []
    if upstream:
        remote = git(repo, "config", f"branch.{branch}.remote")
        merge = git(repo, "config", f"branch.{branch}.merge")
        result = run(repo, "push", "-q", *lease, remote, f"refs/heads/{branch}:{merge}")
        done = f"Pushed {branch} to {remote}" + (", with a lease" if action.force else "")
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


def _replay(directory: Directory, command: list[str], operation: str, what: str, log: Log) -> bool:
    """Runs a rebase or merge. One that fails is aborted, leaving HEAD and the files as they
    were, and logged. Says whether it succeeded."""
    repo = directory.path
    result = run(repo, *command)
    if result.returncode == 0:
        return True
    run(repo, operation, "--abort")
    noun = "Rebase" if operation == "rebase" else "Merge of"
    log(False, f"{noun} {what} stopped at a conflict, so it was undone")
    return False


def _not_clean(directory: Directory) -> str | None:
    """Why HEAD can't be rebased or merged now, or None when it can."""
    repo = directory.path
    if operation := in_progress(repo):
        return f"{operation} is in progress"
    if git(repo, "status", "--porcelain", "--untracked-files=no"):
        return "there are uncommitted changes"
    return None


def _count(repo: Path, *revisions: str) -> int:
    return int(git(repo, "rev-list", "--count", *revisions))
