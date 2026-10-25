"""Asking at the terminal for the integration of each directory that sets none, and setting
the one chosen in its own copy of .config/ianf-repo-tools.toml.

There's no default, so a directory left unset, by skipping or with no terminal to ask at, is
reported as it was and asked again next time.
"""

from collections.abc import Sequence
from pathlib import Path
from typing import assert_never

import repo_settings
from cli_kit import terminal
from cli_kit.colour import YELLOW
from repo_settings import Assignment, Invalid, NewFile, Target, Unchanged, Unlocatable, Written

from repo_list import report, scan
from repo_list.config import SCHEMA, Version
from repo_list.integration import Integration
from repo_list.plugin import Plugin

QUESTION = "How and where does work reach the trunk?"
SKIP = "skip          leave it unset, and ask again next time"


def _options() -> list[str]:
    """What to choose from: each integration, by its name, then skip."""
    return [
        *(
            f"{integration:<10} {integration.icon} {_summary(integration)}"
            for integration in Integration
        ),
        SKIP,
    ]


def _prompt(path: Path) -> str:
    """The question for the directory at path from the root: the path coloured as repo-list lists
    it, and the question in yellow, as its unset integration is listed."""
    colour = terminal.style()
    return f"{report.name(path, colour)}: {colour(YELLOW, QUESTION)}"


def _chosen(index: int | None) -> Integration | None:
    """The integration the option at index sets, or None for skip, or when nothing was chosen."""
    integrations = list(Integration)
    return integrations[index] if index is not None and index < len(integrations) else None


def ask_unset(directories: Sequence[scan.Directory], root: Path, plugins: list[Plugin]) -> None:
    """Asks for the integration of each directory that sets none, in turn, and checks each one set
    again, so it's reported and fixed in that integration."""
    for directory in directories:
        if directory.config_error != scan.NO_INTEGRATION:
            continue
        integration = _chosen(
            terminal.choose(_prompt(directory.path.relative_to(root)), _options())
        )
        if integration is None:
            continue
        directory.config_error = _set(directory.path, integration)
        if directory.config_error is None:
            scan.locate(directory)
            scan.check_all(directory, plugins)


def _set(path: Path, integration: Integration) -> str | None:
    """Sets integration in the settings of the worktree path is in: None once it's set, or what's
    wrong with the file, which is left for a person to fix."""
    written = repo_settings.write(
        Target.THIS_WORKTREE,
        path,
        scan.PURPOSE,
        NewFile(Version.V1, SCHEMA),
        [Assignment((), "integration", integration.value)],
    )
    for result in written:
        match result:
            case Written() | Unchanged():
                pass
            case Invalid() | Unlocatable():
                return " ".join((result.message, *result.details))
            case _:
                assert_never(result)
    return None


def _summary(integration: Integration) -> str:
    match integration:
        case Integration.LOCAL:
            return "here, rebased onto trunk; only trunk pushed"
        case Integration.PR_REBASE:
            return "by pull request, rebased onto trunk"
        case Integration.PR_MERGE:
            return "by pull request, trunk merged in"
        case _:
            assert_never(integration)
