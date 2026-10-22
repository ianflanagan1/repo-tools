"""Report the state of every git repository under a folder.

Lists each repository under the root by its path from the root,
with ✔ when everything is committed and pushed, or ✘ and what needs attention:

  📝 uncommitted files            📦 stashes
  📤 commits on no remote         🔌 no remote
  📥 behind the upstream          📁 not a git repository
  👻 commits on detached HEAD     📡 fetch failed (with --fetch)
  🐘 Packagist (with --packagist) 💥 git failed

Between the path and the problems is the branch checked out, or @ and the commit for a detached
HEAD; the default branch is dimmed.
A folder that holds files but is in no repository is listed as not a git repository. With
--packagist, each package of your Packagist vendor's is checked: not on Packagist, Packagist
lacking a version tag or branch commit that is on origin, or the check failed.
The root and vendor come from the project's config.toml; see config.example.toml.
Ends with a count of those needing attention. Colour is used on a terminal, or with FORCE_COLOR
set, unless NO_COLOR is set.

Exit status: 0 all clean, 1 something needs attention, 2 usage error.
"""

from pathlib import Path

from cli_kit import cli

from repo_list import config, plugins, report, scan


def main(argv: list[str] | None = None) -> int:
    parser = cli.ArgumentParser(
        prog="repo-list",
        description=__doc__,
    )
    parser.add_argument("root", nargs="?", help="default: root in config.toml, or ~/projects")
    parser.add_argument(
        "-f",
        "--fetch",
        action="store_true",
        help="fetch every repository first, in parallel, so behind counts are current",
    )
    parser.add_argument(
        "-p",
        "--packagist",
        action="store_true",
        help="check each package of your vendor's is on Packagist with all that's on origin",
    )
    args = parser.parse_args(argv)
    settings = config.for_command(parser, args.packagist)
    args.root = args.root or settings.root
    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        parser.error(f"not a directory: {args.root}")

    folders = scan.find(root)
    if not folders:
        print(f"No repositories under {root}")
        return 0
    vendor = settings.packagist_vendor if args.packagist else None
    scan.survey(folders, plugins.built_in(vendor), fetch_first=args.fetch)
    return report.show(root, folders)


if __name__ == "__main__":
    raise SystemExit(main())
