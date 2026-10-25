"""github edit <repo> [--description <text>] [--add-topic <topic>]...

Sets a GitHub repo's description and adds topics to it. repo is owner/name, or a name owned by
the account gh is logged in as. Only what differs is sent, and nothing is done when the repo
already matches.

It changes nothing else: not the visibility, the name or the settings, which `gh repo edit`
could also change.
"""

from cli_kit import cli
from cli_kit.outcome import Done, NothingToDo, Precondition

from repo_tools.github import api


def register(subparsers: cli.Subparsers) -> None:
    parser = subparsers.add_parser(
        "edit",
        help="set a repo's description and add topics",
        description=__doc__.split("\n\n", 1)[1],
    )
    parser.add_argument("repo", help="owner/name, or a name owned by you")
    parser.add_argument("--description", help="the repo's new description")
    parser.add_argument(
        "--add-topic",
        dest="topics",
        action="append",
        default=[],
        metavar="topic",
        help="a topic to add; repeat for more",
    )
    parser.set_defaults(run=lambda args: edit(args.repo, args.description, args.topics))


def edit(name: str, description: str | None, topics: list[str]) -> Done | NothingToDo:
    if description is None and not topics:
        raise Precondition("Nothing to change: give --description or --add-topic.")
    if description is not None and len(description) > api.DESCRIPTION_MAX_LENGTH:
        raise Precondition(
            f"The description is {len(description)} characters;"
            f" GitHub allows at most {api.DESCRIPTION_MAX_LENGTH}."
        )
    repo = api.full_name(name)
    if not api.exists(repo):
        raise Precondition(f"gh can't see a repo {repo}.")
    current = api.details(repo)
    new_description = None if description == current.description else description
    new_topics = tuple(topic for topic in dict.fromkeys(topics) if topic not in current.topics)
    if new_description is None and not new_topics:
        return NothingToDo(f"{repo} already has that description and those topics.")
    api.edit(repo, new_description, new_topics)
    return Done("Edited.", f"https://github.com/{repo}")
