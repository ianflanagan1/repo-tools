"""`github <command> ...`. Run it through the ./github launcher."""

import sys

from cli_kit import cli

from repo_tools import git_host_commands
from repo_tools.github.commands import (
    archive,
    delete,
    edit,
    publish,
    release,
    rename,
    view,
    visibility,
)
from repo_tools.github.git_host_api import GitHub

COMMANDS = [
    publish,
    release,
    rename,
    view,
    edit,
    visibility,
    archive,
    delete,
    *git_host_commands.commands(GitHub),
]


def main(argv: list[str] | None = None) -> int:
    return cli.run("github", "Manage GitHub repositories.", COMMANDS, argv)


if __name__ == "__main__":
    sys.exit(main())
