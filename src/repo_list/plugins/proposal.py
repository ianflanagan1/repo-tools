"""🔃 A branch with work for the trunk but no pull request open for it, where work goes by pull
request: one is opened, as a draft, for its author to mark ready.

Checked only for the branch checked out in the directory, once it has an upstream, and only when
the remotes were fetched in this run, as asking the host needs the network: repo-list with
--fetch, and repo-fix. A host repo-tools has no adapter for, such as a plain git server, is
left alone.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import assert_never, final

from repo_list.git import git
from repo_list.hosts import Host, NotOpened, Opened, Unknown, proposal
from repo_list.plugin import Log, Plugin, Problem, Stage
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
    host: str
    reason: str

    def describe(self) -> str:
        return f"🔃 {self.host} couldn't say if {self.branch} has a pull request: {self.reason}"


class Proposal(Plugin):
    name = "proposal"
    stage = Stage.AFTER_PUSH

    def __init__(self, hosts: Callable[[str], Host | None]) -> None:
        self.hosts = hosts

    def check(self, directory: Directory) -> list[Problem]:
        target = _target(directory, self.hosts)
        if target is None:
            return []
        branch, base, host = target
        match host.open_for(branch):
            case True:
                return []
            case False:
                return [NoPullRequest(branch, base)]
            case Unknown(reason):
                return [PullRequestUnknown(branch, host.host, reason)]
            case _ as answer:
                assert_never(answer)

    def fix(self, directory: Directory, problems: list[Problem], log: Log) -> bool:
        target = _target(directory, self.hosts)
        if target is None:
            return True
        branch, base, host = target
        for problem in problems:
            if not isinstance(problem, NoPullRequest):
                continue
            title, body = proposal(branch, _subjects(directory, base, branch))
            match host.open_draft(branch, base, title, body):
                case Opened(url):
                    log(True, f"Opened a draft pull request for {branch}", url)
                case NotOpened(reason):
                    log(False, f"Opening a pull request for {branch} failed", *reason)
                case _ as result:
                    assert_never(result)
        return True


def _target(
    directory: Directory, hosts: Callable[[str], Host | None]
) -> tuple[str, str, Host] | None:
    """The branch checked out, the trunk it proposes into and its host, when the branch is one
    that should have a pull request."""
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
    host = hosts(git(repo, "config", f"remote.{remote}.url", check=False))
    return (branch, trunk, host) if host else None


def _subjects(directory: Directory, base: str, branch: str) -> list[str]:
    remote = git(directory.path, "config", f"branch.{branch}.remote")
    revisions = f"{remote}/{base}..{branch}"
    return git(directory.path, "log", "--reverse", "--format=%s", revisions).splitlines()
