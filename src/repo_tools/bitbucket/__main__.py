"""`bitbucket <command> ...`."""

import sys

from cli_kit import cli

from repo_tools import forge_commands
from repo_tools.bitbucket.commands import delete, publish, release, rename
from repo_tools.bitbucket.forge import Bitbucket

COMMANDS = [publish, release, rename, delete, *forge_commands.commands(Bitbucket)]


def main(argv: list[str] | None = None) -> int:
    return cli.run("bitbucket", "Manage Bitbucket Cloud repositories.", COMMANDS, argv)


if __name__ == "__main__":
    sys.exit(main())
