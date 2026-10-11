"""`github <command> ...`. Run it through the ./github launcher."""

import sys

from cli_kit import cli

from repo_tools.github.commands import archive, delete, publish, release, rename

COMMANDS = [publish, release, rename, archive, delete]


def main(argv: list[str] | None = None) -> int:
    return cli.run("github", "Manage GitHub repositories.", COMMANDS, argv)


if __name__ == "__main__":
    sys.exit(main())
