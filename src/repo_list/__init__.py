"""Report the state of every git repository under a directory.

Lists each repository under the root that needs attention by its path from the root, with ✘
and then what needs attention; with --all, those with everything committed and pushed too,
with ✔ in its place:

  📝 uncommitted files            📦 stashes
  📤 commits on no remote         🔌 no remote
  📥 behind the upstream          📁 not a git repository
  🛬 not landed on the trunk      ⛔ commits on the trunk (PR integration)
  🔄 HEAD behind its base         ⚡ HEAD conflicts with its base
  🔃 no pull request (PR integration, with --fetch)
  👻 commits on detached HEAD     📡 fetch failed (with --fetch)
  🐘 Packagist (with --packagist) 💥 git failed
  🔴 npm (with --npm)             🔧 no integration, or a wrong one

Between the path and the mark is the branch checked out, or @ and the commit for a detached
HEAD; the trunk is dimmed. 🤖 marks a directory a Claude Code session is busy in, and 💤 one
whose .config/ianf-repo-tools.toml sets skip-fix = true; repo-fix leaves both alone.
Before the path are four icons: the integration, 🏠 local, 📏 pr-rebase,
🔀 pr-merge or 🔧 unset; the host, 🐙 GitHub, 🦊 GitLab, 🧺 Bitbucket, 🗻 Codeberg, 🔷 Azure
DevOps, ❔ another or 🔌 no remote; with --fetch, 🌐 public or 🔒 private; and each kind of
package it is, 🐘 Composer, 🔴 npm, 🐍 Python, 🧩 Claude Code plugin or 📋 Copier template,
blank for none; a Python project is a package once another directory pins it from git. Every
worktree shows its own.
Each directory reports on its own HEAD, and the main worktree also on every branch no worktree
has checked out, as the integration says. Each repository sets its own, in its
.config/ianf-repo-tools.toml; there's no default. One that sets none is asked for one on the
terminal, which is set in its copy; skip, or no terminal, leaves it unset, and asks again next
time.
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

from cli_kit import cli, devbox, outcome

from repo_list import ask_integration, config, plugins, report, scan
from repo_tools import packages


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
    # repo-list only checks, so nothing it wires is ever announced.
    pinned = set().union(*(packages.pinned(d.path) for d in directories))
    active = plugins.built_in(vendor, scope, pinned, outcome.starting)
    scan.survey(directories, active, fetch_first=args.fetch)
    ask_integration.ask_unset(directories, root, active)
    return report.show(root, directories, clean_too=args.all)


if __name__ == "__main__":
    raise SystemExit(main())
