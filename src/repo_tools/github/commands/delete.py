"""github delete <repo>

Deletes a GitHub repo, after you type its full name at the terminal to confirm. This can't be
undone. repo is owner/name, or a name owned by the account gh is logged in as. The local clone,
if any, is left alone.

gh's own login never has the delete_repo scope. Deleting uses a separate token that has it,
stored in the system credential store as github-delete-repo-token (see the README), which is
read only after you confirm. On macOS, store it so the keychain asks you each time it's read.
"""

import argparse

from cli_kit import credentials, terminal
from cli_kit.errors import Precondition
from cli_kit.outcome import Done

from repo_tools.github import api

DELETE_TOKEN_SERVICE = "github-delete-repo-token"


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "delete",
        help="delete a repo, after typed confirmation",
        description=__doc__.split("\n\n", 1)[1],
    )
    parser.add_argument("repo", help="owner/name, or a name owned by you")
    parser.set_defaults(run=lambda args: delete(args.repo))


def delete(name: str) -> Done:
    repo = api.full_name(name)
    if not api.exists(repo):
        raise Precondition(f"gh can't see a repo {repo}.")

    typed = terminal.ask(
        f"Delete https://github.com/{repo} ({api.visibility(repo)})? This can't be undone.\n"
        f"Type {repo} to confirm: "
    )
    if typed != repo:
        raise Precondition("Not confirmed, so nothing was deleted.")

    api.delete(repo, credentials.credential(DELETE_TOKEN_SERVICE).token)
    return Done("Deleted.", repo)
