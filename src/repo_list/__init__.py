"""Report the state of every git repository under a directory.

Lists each repository under the root that needs attention by its path from the root, with ✘
and what needs attention; with --all, those with everything committed and pushed too, with ✔:

  📝 uncommitted files            📦 stashes
  📤 commits on no remote         🔌 no remote
  📥 behind the upstream          📁 not a git repository
  🛬 not landed on the trunk      ⛔ commits on the trunk (PR modes)
  🔄 HEAD behind its base         ⚡ HEAD conflicts with its base
  🔃 no pull request (PR modes, with --fetch)
  👻 commits on detached HEAD     📡 fetch failed (with --fetch)
  🐘 Packagist (with --packagist) 💥 git failed
  🟥 npm (with --npm)             🔧 no integration mode, or a wrong one

Between the path and the problems is the branch checked out, or @ and the commit for a detached
HEAD; the default branch is dimmed. 🤖 marks a directory a Claude Code session is busy in.
Between the mark and the path are three icons: the integration mode, 🏠 local, 📏 pr-rebase,
🔀 pr-merge or 🔧 unset; the host, 🐙 GitHub, 🦊 GitLab, 🧺 Bitbucket, 🗻 Codeberg, 🔷 Azure
DevOps, ❔ another or 🔌 no remote; and, with --fetch, 🌐 public or 🔒 private. A linked
worktree leaves them blank, unless its mode differs from its main worktree's.
Each directory reports on its own HEAD, and the main worktree also on every branch no worktree
has checked out, as the integration mode says. Each repository sets its own, under
[repo-tools] in its .workspace.toml; there's no default.
A directory that holds files but is in no repository is listed as not a git repository. With
--packagist, each package of your Packagist vendor's is checked: not on Packagist, Packagist
lacking a version tag or branch commit that is on origin, or the check failed. A Composer
project, an app, isn't a package. With --npm, each package of your npm scope's that isn't private
is checked the same way, for version tags.
The root, vendor and scope come from the project's config.toml; see config.example.toml.
Ends with a count of those needing attention. Colour is used on a terminal, or with FORCE_COLOR
set, unless NO_COLOR is set.

Exit status: 0 all clean, 1 something needs attention, 2 usage error.
"""

from pathlib import Path

from cli_kit import cli, devbox

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
    parser.add_argument(
        "--npm",
        action="store_true",
        help="check each package of your scope's is on npm with every version tag on origin",
    )
    parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="list clean repositories too",
    )
    args = parser.parse_args(argv)
    devbox.use_tools()
    settings = config.for_command(parser, args.packagist, args.npm)
    args.root = args.root or settings.root
    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        parser.error(f"not a directory: {args.root}")

    directories = scan.find(root)
    if not directories:
        print(f"No repositories under {root}")
        return 0
    vendor = settings.packagist_vendor if args.packagist else None
    scope = settings.npm_scope if args.npm else None
    active = plugins.built_in(vendor, scope)
    scan.survey(directories, active, fetch_first=args.fetch)
    return report.show(root, directories, clean_too=args.all)


if __name__ == "__main__":
    raise SystemExit(main())
