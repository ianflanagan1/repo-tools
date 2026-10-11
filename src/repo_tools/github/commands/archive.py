"""github archive <repo>

Archives a GitHub repo, making it read-only. repo is owner/name, or a name owned by the account
gh is logged in as. Skipped when the repo is already archived.

It uses gh's own login: archiving needs no scope that publishing doesn't, and you can undo it
in the repo's settings.
"""

import argparse

from cli_kit.errors import Precondition
from cli_kit.outcome import Done, NothingToDo

from repo_tools.github import api


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "archive",
        help="archive a repo, making it read-only",
        description=__doc__.split("\n\n", 1)[1],
    )
    parser.add_argument("repo", help="owner/name, or a name owned by you")
    parser.set_defaults(run=lambda args: archive(args.repo))


def archive(name: str) -> Done | NothingToDo:
    repo = api.full_name(name)
    if not api.exists(repo):
        raise Precondition(f"gh can't see a repo {repo}.")
    if api.is_archived(repo):
        return NothingToDo(f"{repo} is already archived.")
    api.archive(repo)
    return Done("Archived.", f"https://github.com/{repo}")
