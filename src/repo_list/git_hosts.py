"""The git hosts repo-fix can publish a repository on, which a repository's settings name for its
origin, and telling which one a remote's URL is on.

A repository's .config/ianf-repo-tools.toml names its origin's git host in a table keyed by the
remote's name, [remotes.origin], so that a mirror could later be named beside it without a new
version of the file. Only origin can be named for now. Its git-host can also be none, which keeps
the repository on this computer only: never published, nor asked where to publish it. Its
visibility says who repo-fix publishes it for, public or private, which none can't have.
"""

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import assert_never, final

from repo_list.config import Invalid

ORIGIN = "origin"


class GitHost(StrEnum):
    GITHUB = "github"
    BITBUCKET = "bitbucket"


class Visibility(StrEnum):
    PUBLIC = "public"
    PRIVATE = "private"
    """Private, or GitHub's internal: either way not for everyone to see."""


LOCAL_ONLY = "none"
"""The git-host that keeps a repository on this computer only."""


@final
@dataclass(frozen=True)
class LocalOnly:
    """Origin is on no git host: the repository is kept on this computer only."""


type Origin = GitHost | LocalOnly
"""Where a repository's settings put origin."""


def title(git_host: GitHost) -> str:
    """The git host's name as the user knows it."""
    match git_host:
        case GitHost.GITHUB:
            return "GitHub"
        case GitHost.BITBUCKET:
            return "Bitbucket"
        case _:
            assert_never(git_host)


def domain(git_host: GitHost) -> str:
    match git_host:
        case GitHost.GITHUB:
            return "github.com"
        case GitHost.BITBUCKET:
            return "bitbucket.org"
        case _:
            assert_never(git_host)


def domain_of(url: str) -> str:
    """The domain a remote URL names, in SSH or HTTPS form, in lower case; empty for a path."""
    match = re.match(r"^(?:[a-z+]+://)?(?:[^@/]+@)?([^/:]+)(?=[:/])", url)
    return match.group(1).lower() if match else ""


def git_host_at(url: str) -> GitHost | None:
    """The git host a remote URL is on, or None for another host, or a path."""
    named = domain_of(url)
    for git_host in GitHost:
        known = domain(git_host)
        if named == known or named.endswith("." + known):
            return git_host
    return None


def origin_git_host_in(table: dict, where: str) -> Origin | Invalid | None:
    """Where the settings table puts origin, None when it names nothing, or what's wrong with its
    remotes.

    where says where the remotes are, for the message, such as
    ".config/ianf-repo-tools.toml: remotes".
    """
    remotes = table.get("remotes")
    if remotes is None:
        return None
    if not isinstance(remotes, dict):
        return Invalid(f"{where} must be a table of remotes, such as [remotes.{ORIGIN}]")
    others = sorted(remotes.keys() - {ORIGIN})
    if others:
        return Invalid(f"{where} can only set {ORIGIN} for now, not {', '.join(others)}")
    origin = remotes.get(ORIGIN)
    if origin is None:
        return None
    if not isinstance(origin, dict):
        return Invalid(f"{where}.{ORIGIN} must be a table")
    unknown = sorted(origin.keys() - {"git-host", "visibility"})
    if unknown:
        return Invalid(f"{where}.{ORIGIN} has an unknown setting {', '.join(unknown)}")
    git_host = origin.get("git-host")
    if git_host == LOCAL_ONLY:
        if "visibility" in origin:
            return Invalid(
                f'{where}.{ORIGIN}.visibility can\'t be set with git-host = "{LOCAL_ONLY}",'
                " as it's never published"
            )
        return LocalOnly()
    if git_host not in set(GitHost):
        allowed = ", ".join([*GitHost, LOCAL_ONLY])
        return Invalid(f"{where}.{ORIGIN}.git-host must be one of {allowed}")
    return GitHost(git_host)


def origin_visibility_in(table: dict, where: str) -> Visibility | Invalid | None:
    """Who the settings table publishes origin for, None when it doesn't say, or what's wrong with
    it. The rest of its remotes are origin_git_host_in's to check.

    where says where the remotes are, as for origin_git_host_in.
    """
    remotes = table.get("remotes")
    origin = remotes.get(ORIGIN) if isinstance(remotes, dict) else None
    visibility = origin.get("visibility") if isinstance(origin, dict) else None
    if visibility is None:
        return None
    if visibility not in set(Visibility):
        allowed = ", ".join(Visibility)
        return Invalid(f"{where}.{ORIGIN}.visibility must be one of {allowed}")
    return Visibility(visibility)
