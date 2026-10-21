"""bitbucket delete <repo>

Deletes a Bitbucket repo, after you type its full name at the terminal to confirm. This can't be
undone. repo is workspace/name, or a name in the workspace set in config.toml. The local clone,
if any, is left alone.

The everyday API token never has the delete scope. Deleting uses a separate token that has
only that, stored in the system credential store as bitbucket-delete-token (see the README),
which is read only after you confirm. On macOS, store it so the keychain asks you each time
it's read.
"""

from cli_kit import cli, terminal
from cli_kit.credentials import Token
from cli_kit.outcome import Done, Precondition

from repo_tools.bitbucket import api
from repo_tools.bitbucket.forge import Bitbucket

DELETE_TOKEN = Token(
    service="bitbucket-delete-token",
    name="Bitbucket delete token",
    username="atlassian-email",
    create="Create an API token with scopes at"
    " https://id.atlassian.com/manage-profile/security/api-tokens, choosing Bitbucket and only"
    " the delete:repository:bitbucket scope.",
    confirm_each_read=True,
)


def register(subparsers: cli.Subparsers) -> None:
    parser = subparsers.add_parser(
        "delete",
        help="delete a repo, after typed confirmation",
        description=__doc__.split("\n\n", 1)[1],
    )
    parser.add_argument("repo", help="workspace/name, or a name in the configured workspace")
    parser.set_defaults(run=lambda args: delete(args.repo))


def delete(name: str) -> Done:
    forge = Bitbucket()
    repo = forge.full_name(name).lower()
    existing = forge.client.repository(repo)
    if existing is None:
        raise Precondition(f"No Bitbucket repo {repo}, or the token can't see it.")

    visibility = "private" if existing["is_private"] else "public"
    typed = terminal.ask(
        f"Delete {api.web_url(repo)} ({visibility})? This can't be undone.\n"
        f"Type {repo} to confirm: "
    )
    if typed != repo:
        raise Precondition("Not confirmed, so nothing was deleted.")

    api.Bitbucket(DELETE_TOKEN.read()).delete(repo)
    return Done("Deleted.", repo)
