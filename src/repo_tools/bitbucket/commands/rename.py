"""bitbucket rename <dir> <new-name>

Renames the Bitbucket repo that a clone's origin names, keeping its workspace, and everything
that names it. Each step is skipped when already done, so it is safe to re-run after a failure.

    1. Rename the Bitbucket repo, which gives it the new name's slug
    2. Point the origin remote at the new slug
    3. Point the package on Packagist at the new URL, when the clone is a Composer package that
       Packagist has from this repo. This needs the Packagist main token (see the README).

Bitbucket doesn't redirect the old slug, for git or its API, so other clones must be pointed
at the new one. The clone's directory keeps its name.
"""

import re
from pathlib import Path

from cli_kit import cli, outcome
from cli_kit.outcome import Done, NothingToDo, Precondition
from cli_kit.proc import output

from repo_tools import clone, manifest
from repo_tools.bitbucket import api
from repo_tools.packagist import api as packagist

NAME = re.compile(r"^[A-Za-z0-9._-]+$")


def register(subparsers: cli.Subparsers) -> None:
    parser = subparsers.add_parser(
        "rename",
        help="rename the repo, its origin remote and its Packagist URL",
        description=__doc__.split("\n\n", 1)[1],
    )
    parser.add_argument("dir", type=Path)
    parser.add_argument("name", metavar="new-name", help="the new name, without the workspace")
    parser.set_defaults(run=lambda args: rename(args.dir, args.name))


def rename(directory: Path, new_name: str) -> Done | NothingToDo:
    if not directory.is_dir():
        raise Precondition(f"No such directory: {directory}.")
    if "/" in new_name:
        raise Precondition("Give the new name without the workspace; a rename keeps it.")
    if not NAME.match(new_name):
        raise Precondition("Give a name of letters, digits, dots, dashes and underscores.")
    origin = clone.origin_url(directory)
    if origin is None:
        raise Precondition("No origin remote.", "Run `bitbucket publish` first.")
    named = api.repo_from_url(origin).lower()
    target = f"{named.split('/')[0]}/{new_name.lower()}"

    client = api.connect()
    current = client.repository(named)
    if current is None and client.repository(target) is None:
        raise Precondition(f"No Bitbucket repo {named} or {target}, or the token can't see it.")

    # 1. Bitbucket
    if current is not None and current["full_name"].lower() != target:
        renamed = client.rename(named, new_name).lower()
        if renamed != target:
            raise Precondition(f"Bitbucket named it {renamed}, not {target}.")
        outcome.changed(f"Renamed {named} to {target}")

    # 2. Origin
    if named != target:
        url = api.renamed_url(origin, target)
        output("git", "-C", str(directory), "remote", "set-url", "origin", url)
        outcome.changed(f"Pointed origin at {target}")

    # 3. Packagist
    url = api.web_url(target)
    if (package := manifest.composer_name(directory)) and (stored := packagist.repository(package)):
        if "bitbucket.org" in stored and api.repo_from_url(stored).lower() != target:
            packagist.edit_repository(package, url)
            outcome.changed(f"Pointed {package} on Packagist at {url}")

    if not outcome.changes():
        return NothingToDo(f"Already named {target}.")
    return Done("Renamed.", url)
