"""`npmjs <command> ...`. Run it through the ./npmjs launcher."""

import sys

from cli_kit import cli

from repo_tools.npmjs.commands import publish, wait

COMMANDS = [publish, wait]


def main(argv: list[str] | None = None) -> int:
    return cli.run("npmjs", "Manage npm packages.", COMMANDS, argv)


if __name__ == "__main__":
    sys.exit(main())
