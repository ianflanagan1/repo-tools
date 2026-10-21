"""github delete <repo>

Deletes a GitHub repo, after you type its full name at the terminal to confirm. This can't be
undone. repo is owner/name, or a name owned by the account gh is logged in as. The local clone,
if any, is left alone.

gh's own login never has the delete_repo scope. Deleting uses a separate token that has it,
stored in the system credential store as github-delete-repo-token (see the README), which is
read only after you confirm. On macOS, store it so the keychain asks you each time it's read.
"""

from cli_kit import cli, terminal
from cli_kit.credentials import Token
from cli_kit.outcome import Done, Precondition

from repo_tools.github import api

DELETE_TOKEN = Token(
    service="github-delete-repo-token",
    name="GitHub delete_repo token",
    username="github-username",
    create="Create a classic token with only the delete_repo scope at"
    " https://github.com/settings/tokens.",
    confirm_each_read=True,
)


def register(subparsers: cli.Subparsers) -> None:
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

    api.delete(repo, DELETE_TOKEN.read().token)
    return Done("Deleted.", repo)
