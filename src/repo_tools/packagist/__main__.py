"""`packagist <command> ...`. Run it through the ./packagist launcher."""

import sys

from cli_kit import cli

from repo_tools.packagist.commands import publish, update

COMMANDS = [publish, update]


def main(argv: list[str] | None = None) -> int:
    return cli.run("packagist", "Manage Packagist packages.", COMMANDS, argv)


if __name__ == "__main__":
    sys.exit(main())
