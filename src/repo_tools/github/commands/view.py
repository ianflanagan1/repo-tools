"""github view <repo>

Prints a GitHub repo's visibility, description and topics as one JSON object, then a status
line, so `grep '^{'` keeps only the data. repo is owner/name, or a name owned by the account gh
is logged in as. It changes nothing.
"""

import json

from cli_kit import cli
from cli_kit.outcome import NothingToDo, Precondition

from repo_tools.github import api


def register(subparsers: cli.Subparsers) -> None:
    parser = subparsers.add_parser(
        "view",
        help="show a repo's visibility, description and topics",
        description=__doc__.split("\n\n", 1)[1],
    )
    parser.add_argument("repo", help="owner/name, or a name owned by you")
    parser.set_defaults(run=lambda args: view(args.repo))


def view(name: str) -> NothingToDo:
    repo = api.full_name(name)
    if not api.exists(repo):
        raise Precondition(f"gh can't see a repo {repo}.")
    found = api.details(repo)
    print(
        json.dumps(
            {
                "repo": repo,
                "visibility": found.visibility,
                "description": found.description,
                "topics": list(found.topics),
            }
        )
    )
    topics = "1 topic" if len(found.topics) == 1 else f"{len(found.topics)} topics"
    return NothingToDo(f"{repo} is {found.visibility}, with {topics}.")
