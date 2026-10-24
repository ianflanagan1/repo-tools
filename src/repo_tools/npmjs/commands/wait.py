"""npmjs wait <dir>

Waits until npm has every version tag on origin, which the publish workflow publishes once
`github release` pushes it. Tags older than the package's first version on npm don't count.
Nothing is waited for when npm already has them all, so it is safe to re-run.
"""

import time
from pathlib import Path

from cli_kit import cli
from cli_kit.outcome import Done, Failure, NothingToDo, Precondition

from repo_tools import clone
from repo_tools.github import api as github
from repo_tools.npmjs import api as npm
from repo_tools.npmjs.commands.publish import package_name

WAIT_SECONDS = 600
POLL_SECONDS = 10


def register(subparsers: cli.Subparsers) -> None:
    parser = subparsers.add_parser(
        "wait",
        help="wait until npm has every version tag",
        description=__doc__.split("\n\n", 1)[1],
    )
    parser.add_argument("dir", type=Path)
    parser.set_defaults(run=lambda args: wait(args.dir))


def wait(directory: Path) -> Done | NothingToDo:
    if not directory.is_dir():
        raise Precondition(f"No such directory: {directory}.")
    directory = directory.resolve()
    package = package_name(directory)
    origin = clone.origin_url(directory)
    if origin is None:
        raise Precondition("No origin remote.", "Run `github publish` first.")
    repo = github.repo_from_url(origin)

    lacking = npm.lacks(package, directory)
    if lacking is None:
        raise Precondition(f"{package} isn't on npm.", "Run `npmjs publish` first.")
    url = npm.package_url(package)
    if not lacking:
        return NothingToDo(f"Already published: {url}")

    deadline = time.monotonic() + WAIT_SECONDS
    while lacking := npm.lacks(package, directory):
        if time.monotonic() >= deadline:
            raise Failure(
                f"npm still lacks {', '.join(lacking)}.",
                "The publish workflow may still be running, or it failed. Its runs:",
                f"https://github.com/{repo}/actions/workflows/{npm.WORKFLOW}",
            )
        time.sleep(POLL_SECONDS)
    return Done("Published.", url)
