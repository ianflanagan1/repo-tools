"""github visibility <repo> public|private

Makes a GitHub repo public or private. repo is owner/name, or a name owned by the account gh is
logged in as. Skipped when the repo already has that visibility.

Making a repo private drops its stars and watchers, and leaves any public forks public. It's a
command of its own, rather than part of `github edit`, so that edit can stay allowed where this
can't.
"""

from cli_kit import cli
from cli_kit.outcome import Done, NothingToDo, Precondition

from repo_tools.github import api


def register(subparsers: cli.Subparsers) -> None:
    parser = subparsers.add_parser(
        "visibility",
        help="make a repo public or private",
        description=__doc__.split("\n\n", 1)[1],
    )
    parser.add_argument("repo", help="owner/name, or a name owned by you")
    parser.add_argument("visibility", choices=["public", "private"])
    parser.set_defaults(run=lambda args: set_visibility(args.repo, args.visibility))


def set_visibility(name: str, visibility: str) -> Done | NothingToDo:
    repo = api.full_name(name)
    if not api.exists(repo):
        raise Precondition(f"gh can't see a repo {repo}.")
    if api.visibility(repo) == visibility:
        return NothingToDo(f"{repo} is already {visibility}.")
    api.set_visibility(repo, visibility)
    return Done(f"Made {visibility}.", f"https://github.com/{repo}")
