"""🔃 A branch with work for the trunk but no pull request open for it, where work goes by pull
request: one is opened, as a draft, for its author to mark ready.

Checked only for the branch checked out in the directory, once it has an upstream, and only when
the remotes were fetched in this run, as asking the git host needs the network: repo-list with
--fetch, and repo-fix. A git server repo-tools has no adapter for, such as a plain one, is
left alone.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import assert_never, final

from repo_list import git_hosts
from repo_list.git import git
from repo_list.plugin import Log, Plugin, Problem, Stage
from repo_list.remote_repos import NotOpened, Opened, RemoteRepo, Unknown, proposal
from repo_list.scan import Directory


@final
@dataclass(frozen=True)
class NoPullRequest:
    branch: str
    base: str

    def describe(self) -> str:
        return f"🔃 no pull request for {self.branch}"


@final
@dataclass(frozen=True)
class PullRequestUnknown:
    branch: str
    git_host: str
    reason: str

    def describe(self) -> str:
        return f"🔃 {self.git_host} couldn't say if {self.branch} has a pull request: {self.reason}"


class Proposal(Plugin):
    name = "proposal"
    stage = Stage.AFTER_PUSH

    def __init__(self, remote_repo_at: Callable[[str], RemoteRepo | None]) -> None:
        self.remote_repo_at = remote_repo_at

    def check(self, directory: Directory) -> list[Problem]:
        target = _target(directory, self.remote_repo_at)
        if target is None:
            return []
        branch, base, remote_repo = target
        match remote_repo.open_for(branch):
            case True:
                return []
            case False:
                return [NoPullRequest(branch, base)]
            case Unknown(reason):
                return [PullRequestUnknown(branch, git_hosts.title(remote_repo.git_host), reason)]
            case _ as answer:
                assert_never(answer)

    def fix(self, directory: Directory, problems: list[Problem], log: Log) -> bool:
        target = _target(directory, self.remote_repo_at)
        if target is None:
            return True
        branch, base, remote_repo = target
        for problem in problems:
            if not isinstance(problem, NoPullRequest):
                continue
            title, body = proposal(branch, _subjects(directory, base, branch))
            match remote_repo.open_draft(branch, base, title, body):
                case Opened(url):
                    log(True, f"Opened a draft pull request for {branch}", url)
                case NotOpened(reason):
                    log(False, f"Opening a pull request for {branch} failed", *reason)
                case _ as result:
                    assert_never(result)
        return True


def _target(
    directory: Directory, remote_repo_at: Callable[[str], RemoteRepo | None]
) -> tuple[str, str, RemoteRepo] | None:
    """The branch checked out, the trunk it proposes into and its remote repo, when the branch is
    one that should have a pull request."""
    place = directory.place
    if not (
        place and place.integration and place.integration.by_pull_request and directory.fetched
    ):
        return None
    branch, trunk = place.head, place.trunk
    if branch is None or trunk is None or branch == trunk:
        return None
    repo = directory.path
    upstream = git(repo, "rev-parse", "--quiet", "--abbrev-ref", f"{branch}@{{u}}", check=False)
    remote = git(repo, "config", f"branch.{branch}.remote", check=False)
    if not upstream or not remote:
        return None
    ahead = git(repo, "rev-list", "--count", f"{remote}/{trunk}..{branch}", check=False)
    if not ahead or int(ahead) == 0:
        return None
    remote_repo = remote_repo_at(git(repo, "config", f"remote.{remote}.url", check=False))
    return (branch, trunk, remote_repo) if remote_repo else None


def _subjects(directory: Directory, base: str, branch: str) -> list[str]:
    remote = git(directory.path, "config", f"branch.{branch}.remote")
    revisions = f"{remote}/{base}..{branch}"
    return git(directory.path, "log", "--reverse", "--format=%s", revisions).splitlines()
