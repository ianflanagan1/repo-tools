"""What every code host gives for measuring delivery: its deployments, merged pull requests and
the commits between two revisions, and the files committed to it, in the same shape whichever
host it is.

Each host has an adapter, a subclass of Forge, in its own package: repo_tools.github.forge and
repo_tools.bitbucket.forge. Forge is an abstract class rather than a Protocol so that an adapter
missing a method fails as soon as it's made, without a type checker; tests/repo_tools/
test_forge_contract.py holds every adapter to the same behaviour.

Every time is timezone-aware, in UTC. A repo is named owner/name on every host: on GitHub the
owner is a user or organisation, on Bitbucket a workspace.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class Status(StrEnum):
    """How a deployment went, mapped from each host's own states."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    STOPPED = "stopped"
    """Stopped or abandoned before it finished, which counts neither way."""
    IN_PROGRESS = "in_progress"


@dataclass(frozen=True)
class Deployment:
    id: str
    environment: str
    commit: str
    """The full hash of the commit deployed."""
    status: Status
    started_at: datetime
    finished_at: datetime | None
    """When it reached its status; None while in progress."""
    url: str


@dataclass(frozen=True)
class PullRequest:
    number: int
    title: str
    author: str
    base: str
    """The branch it merged into."""
    opened_at: datetime
    merged_at: datetime
    merge_commit: str | None
    """The commit it landed as on base, or None where the host doesn't say."""
    url: str


@dataclass(frozen=True)
class Commit:
    sha: str
    authored_at: datetime
    """When the change was written. It survives rebases and merges, where the committer date
    doesn't, so it's what lead time is measured from."""
    summary: str
    """The first line of its message."""
    merge: bool
    """Whether it merges branches, such as develop into master. A merge's authored time is when
    the merge was made, not when any change in it was written, so lead time leaves merges out."""


class Forge(ABC):
    """A code host, read for its delivery data. Each method raises Precondition when the repo
    isn't there or the login can't see it, and Failure when the host can't be reached."""

    name: str
    """The host's name as the user knows it, such as "GitHub"."""

    @abstractmethod
    def full_name(self, repo: str) -> str:
        """owner/name for a repo given as owner/name, or as a bare name in the default owner:
        the logged-in user on GitHub, the configured workspace on Bitbucket."""

    @abstractmethod
    def main_branch(self, repo: str) -> str:
        """The repo's main branch, as the host calls the default one."""

    @abstractmethod
    def file(self, repo: str, revision: str, path: str) -> str | None:
        """The text of the file at path in revision, a branch, tag or commit, or None when it
        has none."""

    @abstractmethod
    def environments(self, repo: str) -> list[str]:
        """The names of the repo's deployment environments."""

    @abstractmethod
    def deployments(self, repo: str, environment: str, since: datetime) -> list[Deployment]:
        """The deployments to environment, matched ignoring case, started at or after since,
        newest first."""

    @abstractmethod
    def merged_pull_requests(
        self, repo: str, since: datetime, base: str | None = None
    ) -> list[PullRequest]:
        """The pull requests merged at or after since, into base or into any branch when it's
        None, most recently merged first."""

    @abstractmethod
    def commits_between(self, repo: str, base: str, head: str) -> list[Commit]:
        """The commits reachable from head and not from base, as `git log base..head` gives
        them: newest first. base and head are commit hashes, branches or tags."""
