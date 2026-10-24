"""How work on a repository's branches gets into its trunk, the default branch, and so what each
directory reports about its branches and what repo-fix does about them.

Three modes, each repository setting its own by `integration` under [repo-tools] in its
.workspace.toml, with no default:

- local: work is landed on the trunk by hand, here, and only the trunk is pushed. Other branches
  and detached HEADs are rebased onto the local trunk, and report what's still to land.
- pr-rebase: work reaches the trunk by pull request. The trunk only follows its upstream; a
  branch is rebased onto the trunk on the remote and pushed with a lease.
- pr-merge: as pr-rebase, but the trunk on the remote is merged into a branch, so nothing is
  rewritten or forced.

Each directory reports on its own HEAD, and the main worktree also on every branch no worktree has
checked out, so nothing a repository's worktrees share is reported twice. repo-fix takes the
directory that updates the trunk first, so the others catch up with the trunk as it now is.

Everything here is a pure function of the facts the sync plugin gathers.
"""

from collections.abc import Hashable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import assert_never, final

from repo_list.plugin import count

UNSET = "🔧"
"""The mode's icon when none is set, or the one set doesn't exist."""


class Integration(StrEnum):
    LOCAL = "local"
    PR_REBASE = "pr-rebase"
    PR_MERGE = "pr-merge"

    @property
    def icon(self) -> str:
        match self:
            case Integration.LOCAL:
                return "🏠"
            case Integration.PR_REBASE:
                return "📏"
            case Integration.PR_MERGE:
                return "🔀"
            case _:
                assert_never(self)

    @property
    def by_pull_request(self) -> bool:
        match self:
            case Integration.LOCAL:
                return False
            case Integration.PR_REBASE | Integration.PR_MERGE:
                return True
            case _:
                assert_never(self)


@final
@dataclass(frozen=True)
class Worktree:
    path: Path
    branch: str | None
    """The branch checked out, or None for a detached HEAD."""
    prunable: bool
    """Whether its directory is gone, so its branch is checked out nowhere."""


@final
@dataclass(frozen=True)
class Branch:
    """What a local branch has that its upstream and the trunk lack, and the reverse."""

    name: str
    here: bool
    """Whether it's checked out in this directory."""
    trunk: bool | None
    """Whether it's the trunk, or None when the trunk isn't known."""
    has_upstream: bool
    unpushed: int
    """Its commits on no remote."""
    behind: int
    """Its upstream's commits it lacks, as of the last fetch."""
    unmerged: int
    """Its commits not on the local trunk."""


@final
@dataclass(frozen=True)
class Head:
    """How far HEAD, when it isn't the trunk, is behind the branch it lands on."""

    branch: str | None
    """The branch checked out, or None for a detached HEAD."""
    base: str
    """What it catches up with: the trunk in local mode, the trunk on the remote otherwise."""
    behind_base: int
    conflicts: bool
    """Whether bringing the base's commits in would conflict."""


# --- Problems


@final
@dataclass(frozen=True)
class Unpushed:
    """Commits on a local branch that are on no remote."""

    branch: str
    commits: int

    def describe(self) -> str:
        return f"📤 {self.commits} unpushed on {self.branch}"


@final
@dataclass(frozen=True)
class BehindUpstream:
    """Commits on the branch's upstream that it lacks, as of the last fetch."""

    branch: str
    commits: int

    def describe(self) -> str:
        return f"📥 {self.commits} behind on {self.branch}"


@final
@dataclass(frozen=True)
class OnTrunk:
    """Commits made on the trunk where work goes by pull request, which belong on a branch."""

    branch: str
    commits: int

    def describe(self) -> str:
        return f"⛔ {count(self.commits, 'commit')} on {self.branch}"


@final
@dataclass(frozen=True)
class Unmerged:
    """Commits on a branch that aren't on the trunk yet: work still to land."""

    branch: str
    commits: int

    def describe(self) -> str:
        return f"🛬 {self.commits} unmerged on {self.branch}"


@final
@dataclass(frozen=True)
class BehindBase:
    """Commits on the base that HEAD lacks, which catching up brings in."""

    base: str
    commits: int

    def describe(self) -> str:
        return f"🔄 {self.commits} behind {self.base}"


@final
@dataclass(frozen=True)
class Conflicts:
    """HEAD is behind its base, and bringing the base's commits in would conflict."""

    base: str

    def describe(self) -> str:
        return f"⚡ conflicts with {self.base}"


type BranchProblem = Unpushed | BehindUpstream | OnTrunk | Unmerged
type HeadProblem = BehindBase | Conflicts


def assess_branch(branch: Branch, mode: Integration, has_remote: bool) -> list[BranchProblem]:
    """What needs attention about the branch.

    With no remote, nothing is counted as unpushed: the missing remote is reported instead.
    """
    found: list[BranchProblem] = []
    if has_remote and branch.unpushed:
        match _role(branch, mode):
            case _Role.PUSHED:
                found.append(Unpushed(branch.name, branch.unpushed))
            case _Role.PROTECTED_TRUNK:
                found.append(OnTrunk(branch.name, branch.unpushed))
            case _Role.LANDED:
                pass
            case _ as role:
                assert_never(role)
    if branch.behind:
        found.append(BehindUpstream(branch.name, branch.behind))
    if _role(branch, mode) is _Role.LANDED and branch.unmerged:
        found.append(Unmerged(branch.name, branch.unmerged))
    return found


def assess_head(head: Head, mode: Integration) -> list[HeadProblem]:
    """What needs attention about how far HEAD is behind its base.

    Where work goes by pull request a detached HEAD isn't caught up: it can't be pushed or
    proposed until it's on a branch, which is for you to name.
    """
    if head.branch is None and mode.by_pull_request:
        return []
    if not head.behind_base:
        return []
    return [Conflicts(head.base)] if head.conflicts else [BehindBase(head.base, head.behind_base)]


# --- What repo-fix does


@final
@dataclass(frozen=True)
class FastForward:
    branch: str
    here: bool
    """Whether it's checked out in this directory, so its files move with it."""


@final
@dataclass(frozen=True)
class RebaseOnUpstream:
    """Replays the trunk's own commits onto what its upstream has gained: a pull with rebase."""

    branch: str


@final
@dataclass(frozen=True)
class Diverged:
    """Both ahead of and behind its upstream, and left alone."""

    branch: str


@final
@dataclass(frozen=True)
class CatchUp:
    base: str
    rebase: bool
    """Rebase HEAD onto the base, or else merge the base into it."""


@final
@dataclass(frozen=True)
class WouldConflict:
    """Behind its base, but catching up would conflict, so it's left for you."""

    base: str


@final
@dataclass(frozen=True)
class Push:
    branch: str
    force: bool
    """With a lease, for a branch rebased since it was last pushed."""


type Pull = FastForward | RebaseOnUpstream | Diverged


def plan_pulls(branches: Sequence[Branch], mode: Integration) -> list[Pull]:
    """How each branch behind its upstream is brought level with it, in the branches' order.

    Nothing is forced. A branch both behind and with commits of its own has diverged, and is
    left alone, except the trunk checked out here in local mode: its own commits are rebased
    onto its upstream, as a pull with rebase would.
    """
    pulls: list[Pull] = []
    for branch in branches:
        if not branch.behind:
            continue
        if not branch.unpushed:
            pulls.append(FastForward(branch.name, branch.here))
        elif mode is Integration.LOCAL and branch.trunk and branch.here:
            pulls.append(RebaseOnUpstream(branch.name))
        else:
            pulls.append(Diverged(branch.name))
    return pulls


def plan_catch_up(head: Head, mode: Integration) -> CatchUp | WouldConflict | None:
    """How HEAD catches up with its base, or None when there's nothing to bring in."""
    match assess_head(head, mode):
        case []:
            return None
        case [Conflicts(base)]:
            return WouldConflict(base)
        case _:
            return CatchUp(head.base, rebase=mode is not Integration.PR_MERGE)


def plan_pushes(branches: Sequence[Branch], mode: Integration) -> list[Push]:
    """Which branches are pushed, in the branches' order: in local mode only the trunk, and
    where work goes by pull request every branch but the trunk.

    A diverged branch is pushed only in pr-rebase mode, with a lease, as its own rebase onto the
    trunk is what made it diverge; git refuses the push if its upstream has commits that were
    never fetched here.
    """
    pushes: list[Push] = []
    for branch in branches:
        if not branch.unpushed or _role(branch, mode) is not _Role.PUSHED:
            continue
        force = mode is Integration.PR_REBASE and branch.trunk is False
        if branch.behind and not force:
            continue
        pushes.append(Push(branch.name, force))
    return pushes


def mode_icon(mode: Integration | None, is_main: bool, main_mode: Integration | None) -> str | None:
    """The icon for a worktree's integration mode, or None for a linked worktree whose mode is
    its main worktree's, which says it already."""
    if not is_main and mode == main_mode:
        return None
    return mode.icon if mode else UNSET


def branches_to_check(
    head: str | None,
    is_main: bool,
    branches: Sequence[str],
    worktrees: Sequence[Worktree],
    trunk: str | None,
) -> list[str]:
    """The branches a directory reports on: its own, once it has a commit, and in the main worktree
    every branch no worktree has checked out. The trunk comes first, so it's brought level
    before any branch is caught up with it, then the rest in name order."""
    checked_out = {w.branch for w in worktrees if w.branch and not w.prunable}
    chosen = {head} if head in branches else set()
    if is_main:
        chosen |= {b for b in branches if b not in checked_out}
    return sorted(chosen, key=lambda b: (b != trunk, b))


def fix_order[K: Hashable, G: Hashable](
    directories: Sequence[tuple[K, G | None, str | None, bool]], trunks: Mapping[G, str | None]
) -> list[K]:
    """The order repo-fix takes directories in, given each as (key, repository, HEAD's branch,
    whether it's the main worktree), and each repository's trunk.

    Each repository's directories go together, at the place of its first, and the directory that
    updates the trunk goes first among them: the one with it checked out, or else the main
    worktree, which updates it as a branch no worktree has. The rest keep their order. A directory
    in no repository is a repository of its own.
    """
    groups: dict[object, list[tuple[K, G | None, str | None, bool]]] = {}
    for directory in directories:
        key, repo, _, _ = directory
        groups.setdefault(key if repo is None else ("repo", repo), []).append(directory)

    order: list[K] = []
    for members in groups.values():
        repo = members[0][1]
        trunk = trunks.get(repo) if repo is not None else None
        holders = [m for m in members if trunk and m[2] == trunk] or [m for m in members if m[3]]
        first = holders[:1]
        order.extend(m[0] for m in first + [m for m in members if m not in first])
    return order


class _Role(StrEnum):
    PUSHED = "pushed"
    """Its commits go to its upstream."""
    PROTECTED_TRUNK = "protected trunk"
    """The trunk, where work goes by pull request: nothing is committed or pushed on it."""
    LANDED = "landed"
    """A branch whose work is landed on the trunk here, by hand, and never pushed."""


def _role(branch: Branch, mode: Integration) -> _Role:
    if branch.trunk is None:
        return _Role.PUSHED
    match mode:
        case Integration.LOCAL:
            return _Role.PUSHED if branch.trunk else _Role.LANDED
        case Integration.PR_REBASE | Integration.PR_MERGE:
            return _Role.PROTECTED_TRUNK if branch.trunk else _Role.PUSHED
        case _:
            assert_never(mode)
