"""packagist update <dir>

Asks Packagist to update a package it already has from its GitHub repo, then waits until it
offers every version tag and the latest commit of every branch on origin. Nothing is asked when
it already does, so it is safe to re-run.

The webhook `packagist publish` adds keeps Packagist up to date on each push; this is for when
it hasn't, such as a package published before its webhook was added.
"""

import argparse
import time
from pathlib import Path

from cli_kit import outcome
from cli_kit.errors import Failure, Precondition
from cli_kit.outcome import Done, NothingToDo

from repo_tools.github import api as github
from repo_tools.packagist import api as packagist
from repo_tools.packagist.commands.publish import package_name

WAIT_SECONDS = 120
POLL_SECONDS = 5


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "update",
        help="update the package from GitHub, and wait for it",
        description=__doc__.split("\n\n", 1)[1],
    )
    parser.add_argument("dir", type=Path)
    parser.set_defaults(run=lambda args: update(args.dir))


def update(directory: Path) -> Done | NothingToDo:
    if not directory.is_dir():
        raise Precondition(f"No such directory: {directory}.")
    directory = directory.resolve()
    package = package_name(directory)
    if github.origin_url(directory) is None:
        raise Precondition("No origin remote.", "Run `github publish` first.")

    lacking = packagist.lacks(package, directory)
    if lacking is None:
        raise Precondition(f"{package} isn't on Packagist.", "Run `packagist publish` first.")
    url = packagist.package_url(package)
    if not lacking:
        return NothingToDo(f"Already up to date: {url}")

    packagist.update(package)
    outcome.changed(f"Asked Packagist to update {package}")
    deadline = time.monotonic() + WAIT_SECONDS
    while lacking := packagist.lacks(package, directory):
        if time.monotonic() >= deadline:
            raise Failure(
                f"Packagist still lacks {', '.join(lacking)}.",
                "It may still be queued, or Packagist may have rejected it, such as for an invalid",
                "composer.json at that version. The package's page says which:",
                url,
            )
        time.sleep(POLL_SECONDS)
    return Done("Updated.", url)
