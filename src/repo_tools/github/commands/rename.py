"""github rename <dir> <new-name>

Renames the GitHub repo that a clone's origin names, keeping its owner, and everything that
names it. Each step is skipped when already done, so it is safe to re-run after a failure.

    1. Rename the GitHub repo
    2. Point the origin remote at the new name
    3. Point the package on Packagist at the new URL, when the clone is a Composer package that
       Packagist has. This needs the Packagist main token (see the README).

GitHub redirects the old name to the new one, for git, web links and the API, until a repo
takes the old name. Packagist matches the webhook's pushes to a package by its repository URL,
so it is pointed at the new one too. The clone's folder keeps its name.
"""

from pathlib import Path

from cli_kit import cli, outcome
from cli_kit.outcome import Done, NothingToDo, Precondition
from cli_kit.proc import output

from repo_tools import clone, manifest
from repo_tools.github import api
from repo_tools.packagist import api as packagist


def register(subparsers: cli.Subparsers) -> None:
    parser = subparsers.add_parser(
        "rename",
        help="rename the repo, its origin remote and its Packagist URL",
        description=__doc__.split("\n\n", 1)[1],
    )
    parser.add_argument("dir", type=Path)
    parser.add_argument("name", metavar="new-name", help="the new name, without the owner")
    parser.set_defaults(run=lambda args: rename(args.dir, args.name))


def rename(directory: Path, new_name: str) -> Done | NothingToDo:
    if not directory.is_dir():
        raise Precondition(f"No such directory: {directory}.")
    if "/" in new_name:
        raise Precondition("Give the new name without the owner; a rename keeps the owner.")
    origin = clone.origin_url(directory)
    if origin is None:
        raise Precondition("No origin remote.", "Run `github publish` first.")
    named = api.repo_from_url(origin)
    current = api.current_name(named)
    if current is None:
        raise Precondition(f"gh can't see a repo {named}.")
    target = f"{current.split('/')[0]}/{new_name}"

    # 1. GitHub
    if current != target:
        api.rename(current, new_name)
        outcome.changed(f"Renamed {current} to {target}")

    # 2. Origin
    if named != target:
        output(
            "git",
            "-C",
            str(directory),
            "remote",
            "set-url",
            "origin",
            api.renamed_url(origin, target),
        )
        outcome.changed(f"Pointed origin at {target}")

    # 3. Packagist
    url = f"https://github.com/{target}"
    if (package := manifest.composer_name(directory)) and (stored := packagist.repository(package)):
        if api.repo_from_url(stored) != target:
            packagist.edit_repository(package, url)
            outcome.changed(f"Pointed {package} on Packagist at {url}")

    if not outcome.changes():
        return NothingToDo(f"Already named {target}.")
    return Done("Renamed.", url)
