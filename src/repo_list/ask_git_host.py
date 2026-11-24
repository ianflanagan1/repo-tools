"""Asking at the terminal, before repo-fix publishes, for the git host of each repository that has
no remote and whose .config/ianf-repo-tools.toml puts origin on none, and setting the one chosen
in its own copy, as [remotes.origin] git-host.

A git host is only asked for when there's no remote to tell it by: once origin exists, it says where
the repository is, and repo-list reports a git host set that differs from it. A repository with
direct integration can also be kept on this computer only, setting git-host none, after which it
isn't asked again; one integrated by pull request needs a remote. A repository left unset, by
skipping or with no terminal to ask at, isn't published, and is asked again next time.
"""

from collections.abc import Sequence
from pathlib import Path
from typing import assert_never

from cli_kit import terminal
from cli_kit.colour import YELLOW
from repo_settings import Assignment

from repo_list import git_hosts, report, scan
from repo_list.ask_integration import write_setting
from repo_list.git import git
from repo_list.git_hosts import LOCAL_ONLY, ORIGIN, GitHost, LocalOnly, Origin
from repo_list.integration import Integration
from repo_list.plugin import Plugin
from repo_list.plugins import remote
from repo_list.remote_repos import git_host_icon

QUESTION = f"Which git host should {ORIGIN} be published on?"
KEEP_LOCAL = (
    f"{LOCAL_ONLY:<10} {remote.LOCAL_ONLY} keep it on this computer only, and never ask again"
)
SKIP = "skip          leave it unpublished, and ask again next time"


def _choices(integration: Integration | None) -> list[tuple[str, Origin | None]]:
    """What to choose from, each option and where it puts origin: each git host, by its name;
    none, with direct integration, as only that works without a remote; then skip."""
    git_host_choices: list[tuple[str, Origin | None]] = [
        (
            f"{git_host:<10} {git_host_icon(f'https://{git_hosts.domain(git_host)}/')}"
            f" {git_hosts.title(git_host)}",
            git_host,
        )
        for git_host in GitHost
    ]
    local = [(KEEP_LOCAL, LocalOnly())] if integration is Integration.DIRECT else []
    return [*git_host_choices, *local, (SKIP, None)]


def _prompt(path: Path) -> str:
    """The question for the directory at path from the root: the path coloured as repo-list lists
    it, and the question in yellow."""
    colour = terminal.style()
    return f"{report.name(path, colour)}: {colour(YELLOW, QUESTION)}"


def _unset(directory: scan.Directory) -> bool:
    """Whether repo-fix would publish the directory, but its settings name no git host to do it on:
    a repository it would fix, with settings it can read, and no remote."""
    place = directory.place
    return (
        place is not None
        and not directory.config_error
        and not place.skip_fix
        and not place.claude_working
        and place.origin is None
        and not git(directory.path, "remote")
    )


def ask_unset(directories: Sequence[scan.Directory], root: Path, plugins: list[Plugin]) -> None:
    """Asks for the git host of each directory with no remote that names none, in turn, and checks
    each one set again, so it's published there, or kept local."""
    for directory in directories:
        if not _unset(directory) or directory.place is None:
            continue
        choices = _choices(directory.place.integration)
        prompt = _prompt(directory.path.relative_to(root))
        index = terminal.choose(prompt, [option for option, _ in choices])
        origin = None if index is None else choices[index][1]
        if origin is None:
            continue
        directory.config_error = write_setting(
            directory.path, Assignment(("remotes", ORIGIN), "git-host", _value(origin))
        )
        if directory.config_error is None:
            scan.locate(directory)
            scan.check_all(directory, plugins)


def _value(origin: Origin) -> str:
    """The git-host setting that puts origin there."""
    match origin:
        case GitHost():
            return origin.value
        case LocalOnly():
            return LOCAL_ONLY
        case _:
            assert_never(origin)
