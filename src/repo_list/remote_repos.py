"""A remote repository, on its git host such as GitHub: whether it's public, and, where work
goes by pull request, whether a branch has one open, and opening one as a draft.

RemoteRepo is the port; GitHub's adapter goes through gh, Bitbucket's through its API. Each
turns the git host's failures into values, so a git host that can't be reached is reported, not
raised.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, assert_never, final

from cli_kit.outcome import Problem as Refused

from repo_list.git_hosts import GitHost, Visibility, domain_of, git_host_at
from repo_tools.bitbucket import api as bitbucket
from repo_tools.github import api as github


@final
@dataclass(frozen=True)
class Opened:
    url: str


@final
@dataclass(frozen=True)
class Unknown:
    """The git host couldn't say, such as when no token is stored or it lacks a scope."""

    reason: str


@final
@dataclass(frozen=True)
class NotOpened:
    reason: tuple[str, ...]
    """What the git host said, line by line."""


class RemoteRepo(Protocol):
    git_host: GitHost

    def visibility(self) -> Visibility | Unknown:
        """Who can see the repository, or why the git host couldn't say."""
        ...

    def open_for(self, branch: str) -> bool | Unknown:
        """Whether branch has a pull request open, or why the git host couldn't say."""
        ...

    def open_draft(self, branch: str, base: str, title: str, body: str) -> Opened | NotOpened:
        """Opens a draft pull request from branch into base."""
        ...


# The icon of each git host a remote URL can name, by its domain, icons from Unicode 11 or earlier.
GIT_HOST_ICONS = {
    "github.com": "🐙",
    "gitlab.com": "🦊",
    "bitbucket.org": "🧺",
    "codeberg.org": "🗻",
    "dev.azure.com": "🔷",
    "visualstudio.com": "🔷",
}
NO_GH = "gh isn't installed"
OTHER_GIT_HOST = "❔"
"""Any other git host or server, such as a company's own, or a path on this machine."""


def git_host_icon(url: str) -> str:
    """The icon of the git host a remote URL names, in SSH or HTTPS form."""
    domain = domain_of(url)
    for known, icon in GIT_HOST_ICONS.items():
        if domain == known or domain.endswith("." + known):
            return icon
    return OTHER_GIT_HOST


def for_remote(url: str) -> RemoteRepo | None:
    """The repo at remote url, or None on a git host or server there's no adapter for, such as a
    plain git server."""
    git_host = git_host_at(url)
    try:
        match git_host:
            case GitHost.GITHUB:
                return GitHub(github.repo_from_url(url))
            case GitHost.BITBUCKET:
                return Bitbucket(bitbucket.repo_from_url(url))
            case None:
                return None
            case _:
                assert_never(git_host)
    except Refused:
        return None


def proposal(branch: str, subjects: Sequence[str]) -> tuple[str, str]:
    """The title and body of a pull request of branch's commits, given their subjects oldest
    first: one commit's subject, or else the branch's name, then a list of the subjects."""
    title = subjects[0] if len(subjects) == 1 else branch
    body = "\n".join(f"- {subject}" for subject in subjects)
    return title, body


class GitHub:
    git_host = GitHost.GITHUB

    def __init__(self, repo: str) -> None:
        self.repo = repo

    def visibility(self) -> Visibility | Unknown:
        try:
            said = github.visibility(self.repo)
        except Refused as refused:
            return Unknown(_said(refused))
        except FileNotFoundError:
            return Unknown(NO_GH)
        return Visibility.PUBLIC if said == "public" else Visibility.PRIVATE

    def open_for(self, branch: str) -> bool | Unknown:
        try:
            return github.open_pull_requests(self.repo, branch) > 0
        except Refused as refused:
            return Unknown(_said(refused))
        except FileNotFoundError:
            return Unknown(NO_GH)
        except ValueError:
            return Unknown("gh's answer wasn't a count")

    def open_draft(self, branch: str, base: str, title: str, body: str) -> Opened | NotOpened:
        try:
            return Opened(github.create_draft_pull_request(self.repo, branch, base, title, body))
        except Refused as refused:
            return NotOpened((refused.message, *refused.details))
        except FileNotFoundError:
            return NotOpened((NO_GH,))


class Bitbucket:
    git_host = GitHost.BITBUCKET

    def __init__(self, repo: str) -> None:
        self.repo = repo

    def visibility(self) -> Visibility | Unknown:
        try:
            found = bitbucket.connect().repository(self.repo)
        except Refused as refused:
            return Unknown(_said(refused))
        if found is None:
            return Unknown(f"Bitbucket has no {self.repo} the token can see")
        return Visibility.PRIVATE if found.get("is_private") else Visibility.PUBLIC

    def open_for(self, branch: str) -> bool | Unknown:
        try:
            return bitbucket.connect().open_pull_requests(self.repo, branch) > 0
        except Refused as refused:
            return Unknown(_said(refused))

    def open_draft(self, branch: str, base: str, title: str, body: str) -> Opened | NotOpened:
        try:
            api = bitbucket.connect()
            return Opened(api.create_draft_pull_request(self.repo, branch, base, title, body))
        except Refused as refused:
            return NotOpened((refused.message, *refused.details))


def _said(refused: Refused) -> str:
    """What the git host or the credential store said, on one line."""
    return " ".join([refused.message, *refused.details])
