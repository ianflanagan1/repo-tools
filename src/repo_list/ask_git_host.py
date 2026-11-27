"""Asking at the terminal, before repo-fix publishes, for the git host of each repository that has
no remote and whose .config/ianf-repo-tools.toml puts origin on none, and setting the one chosen
in its own copy, as [remotes.origin] git-host; then, once it has a git host, who can see it, as
[remotes.origin] visibility, if its copy doesn't say. Visibility is asked even of a repository
whose git host was set before, so none is published public without being asked.

A git host is only asked for when there's no remote to tell it by. A repository with direct
integration can also be kept on this computer only, setting git-host none, after which it isn't
asked again; one integrated by pull request needs a remote. A repository left unset, by skipping
or with no terminal to ask at, isn't published, and is asked again next time; so is one whose
visibility is left unset.

A repository already published on a git host must say so in its settings too, which repo-list
reports when they don't. Who can see it is asked, offering first who the git host says can see it
now, so a repository public by mistake isn't kept so unseen, and with the answer its git host is
set, from origin's URL, without asking; skipping leaves both unset. Only the worktree on the trunk
is asked and set, as the setting is the repository's, which the others catch up with.
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
from repo_list.git_hosts import LOCAL_ONLY, ORIGIN, GitHost, LocalOnly, Origin, Visibility
from repo_list.integration import Integration
from repo_list.plugin import Plugin
from repo_list.plugins import remote
from repo_list.remote_repos import git_host_icon

QUESTION = f"Which git host should {ORIGIN} be published on?"
KEEP_LOCAL = (
    f"{LOCAL_ONLY:<10} {remote.LOCAL_ONLY} keep it on this computer only, and never ask again"
)
SKIP = "skip          leave it unpublished, and ask again next time"
UNSAID_SKIP = "skip          leave it unset, and ask again next time"


def visibility_question(git_host: GitHost) -> str:
    return f"Who should see {ORIGIN} on {git_hosts.title(git_host)}?"


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


def _visibility_choices(
    git_host: GitHost, seen: Visibility | None
) -> list[tuple[str, Visibility | None]]:
    """Who can see the repository, each option and the visibility it sets, the one the git host
    has now first, when it said; then skip."""
    now = f" (as {git_hosts.title(git_host)} has it now)"
    choices = [
        (f"{Visibility.PUBLIC:<10} {remote.icon(Visibility.PUBLIC)} anyone", Visibility.PUBLIC),
        (
            f"{Visibility.PRIVATE:<10} {remote.icon(Visibility.PRIVATE)} only those given access",
            Visibility.PRIVATE,
        ),
    ]
    ordered = sorted(choices, key=lambda choice: choice[1] is not seen)
    return [
        *((option + (now if v is seen else ""), v) for option, v in ordered),
        (SKIP, None),
    ]


def _prompt(path: Path, question: str) -> str:
    """The question for the directory at path from the root: the path coloured as repo-list lists
    it, and the question in yellow."""
    colour = terminal.style()
    return f"{report.name(path, colour)}: {colour(YELLOW, question)}"


def _unpublished(directory: scan.Directory) -> scan.Place | None:
    """The directory's place, when repo-fix would publish it: a repository it would fix, with
    settings it can read, no remote, and not kept local; otherwise None."""
    place = directory.place
    if (
        place is None
        or directory.config_error
        or place.skip_fix
        or place.claude_working
        or isinstance(place.origin, LocalOnly)
        or git(directory.path, "remote")
    ):
        return None
    return place


def _choose[T](
    directory: scan.Directory, root: Path, question: str, choices: list[tuple[str, T | None]]
) -> T | None:
    """What's chosen for the directory, or None when it's skipped or there's no terminal."""
    prompt = _prompt(directory.path.relative_to(root), question)
    index = terminal.choose(prompt, [option for option, _ in choices])
    return None if index is None else choices[index][1]


def _set(directory: scan.Directory, setting: str, value: str) -> bool:
    """Sets the [remotes.origin] setting in the directory's settings, and reads them again. Says
    whether it worked; when not, what's wrong is its config error."""
    directory.config_error = write_setting(
        directory.path, Assignment(("remotes", ORIGIN), setting, value)
    )
    if directory.config_error is not None:
        return False
    scan.locate(directory)
    return directory.config_error is None


def ask_unset(directories: Sequence[scan.Directory], root: Path, plugins: list[Plugin]) -> None:
    """Asks, in turn, for the git host of each directory with no remote that names none, then
    who can see each one on a git host that doesn't say, and checks each one set again, so it's
    published there, or kept local."""
    for directory in directories:
        place = _unpublished(directory)
        if place is None:
            continue
        changed = False
        if place.origin is None:
            origin = _choose(directory, root, QUESTION, _choices(place.integration))
            if origin is None or not _set(directory, "git-host", _value(origin)):
                continue
            changed, place = True, directory.place
        if place is not None and isinstance(place.origin, GitHost) and place.visibility is None:
            question = visibility_question(place.origin)
            choices = _visibility_choices(place.origin, None)
            visibility = _choose(directory, root, question, choices)
            if visibility is not None and _set(directory, "visibility", visibility.value):
                changed = True
        if changed:
            scan.check_all(directory, plugins)


def ask_published(directories: Sequence[scan.Directory], root: Path, plugins: list[Plugin]) -> None:
    """Sets what's missing of origin's settings in each worktree on its trunk whose origin is on
    a git host its settings don't say all of: who can see it, asked in turn unless they say, and
    with it the git host, from origin's URL; then checks each one set again. One skipped, or with
    no terminal to ask at, is left as it was."""
    for directory in directories:
        unsaid = _unsaid(directory)
        place = directory.place
        if unsaid is None or place is None:
            continue
        visibility = place.visibility
        if visibility is None:
            question = visibility_question(unsaid.git_host)
            choices = [
                *_visibility_choices(unsaid.git_host, unsaid.seen)[:-1],
                (UNSAID_SKIP, None),
            ]
            visibility = _choose(directory, root, question, choices)
        if visibility is None:
            continue
        written = "git-host" not in unsaid.unset or _set(
            directory, "git-host", unsaid.git_host.value
        )
        if written and "visibility" in unsaid.unset:
            written = _set(directory, "visibility", visibility.value)
        if written:
            scan.check_all(directory, plugins)


def _unsaid(directory: scan.Directory) -> remote.OriginUnsaid | None:
    """What the directory's settings don't say of origin on its git host, when repo-fix would set
    it: in a worktree on the trunk it would fix, with settings it can read."""
    place = directory.place
    if (
        place is None
        or directory.config_error
        or place.skip_fix
        or place.claude_working
        or place.head is None
        or place.head != place.trunk
    ):
        return None
    found = directory.found.get(remote.Remote.name, [])
    return next((p for p in found if isinstance(p, remote.OriginUnsaid)), None)


def _value(origin: Origin) -> str:
    """The git-host setting that puts origin there."""
    match origin:
        case GitHost():
            return origin.value
        case LocalOnly():
            return LOCAL_ONLY
        case _:
            assert_never(origin)
