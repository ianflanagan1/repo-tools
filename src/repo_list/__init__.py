"""Report the state of one git repository, or of every one under a directory.

path is a repository, or a directory to search, its root. Lists each repository that needs
attention by its path from the root, or for a repository given, its parent, with ✘
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
  🧭 origin isn't on the git host .config/ianf-repo-tools.toml puts it on
  🔖 commits since the latest version, and 🔗 a lock file behind on a package of yours (with a
     package flag)

Between the path and the mark is the branch checked out, or @ and the commit for a detached
HEAD; the trunk is dimmed. 🤖 marks a directory a Claude Code session is busy in, and 💤 one
whose .config/ianf-repo-tools.toml sets skip-fix = true; repo-fix leaves both alone.
Before the path are four icons: the integration, 🏠 direct, 📏 pr-rebase,
🔀 pr-merge or 🔧 unset; the git host, 🐙 GitHub, 🦊 GitLab, 🧺 Bitbucket, 🗻 Codeberg, 🔷 Azure
DevOps, ❔ another, 🔌 no remote, or 💻 none, kept on this computer by git-host = "none" in
[remotes.origin]; with --fetch, 🌐 public or 🔒 private; and each kind of dependency it is,
🐘 Composer, 🔴 npm, 🐍 Python, 🐹 Go module, 📋 Copier template or ⛄ Nix flake, blank for none;
a Python project or Go module is one once another directory pins it. Every worktree shows its
own.
Each directory reports on its own HEAD, and the main worktree also on every branch no worktree
has checked out, as the integration says. Each repository sets its own, in its
.config/ianf-repo-tools.toml; there's no default. One that sets none is asked for one on the
terminal, which is set in its copy; skip, or no terminal, leaves it unset, and asks again next
time.
A directory that holds files but is in no repository is listed as not a git repository. With
--packagist, each package of your Packagist vendor's is checked: not on Packagist, Packagist
lacking a version tag or branch commit that is on origin, or the check failed. A Composer
project, an app, isn't a package. With --npm, each package of your npm scope's that isn't private
is checked the same way, for version tags. With --python, each Python package another
repository here pins. --dependencies does all of these. For each, on the trunk with direct
integration: a package never released, or with commits since its latest version tag that change
more than lock files, for Composer and npm; and a lock file holding a package of yours from
another repository here at less than its highest version tag, or for Python than its trunk.
The root, vendor and scope come from the project's config.toml; see config.example.toml.
Ends with a count of those needing attention. Colour is used on a terminal, or with FORCE_COLOR
set, unless NO_COLOR is set.

Exit status: 0 all clean, 1 something needs attention, 2 usage error.
"""

from pathlib import Path

from cli_kit import cli, devbox, outcome

from repo_list import ask_integration, ecosystems, plugins, report, scan
from repo_tools import dependencies


def main(argv: list[str] | None = None) -> int:
    parser = cli.ArgumentParser(
        prog="repo-list",
        description=__doc__,
    )
    parser.add_argument(
        "path",
        nargs="?",
        help="a repository, or a directory to search (default: root in config.toml, or ~/projects)",
    )
    parser.add_argument(
        "-f",
        "--fetch",
        action="store_true",
        help="fetch every repository first, in parallel, so behind counts are current",
    )
    ecosystems.add_flags(
        parser,
        lambda e: f"check {ecosystems.packages_of(e)} is released, published and upgraded",
        "check every kind of dependency, as each flag above does",
    )
    parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="list clean repositories too",
    )
    args = parser.parse_args(argv)
    devbox.use_tools()
    chosen = ecosystems.chosen(args)
    settings = ecosystems.settings_for(parser, chosen)
    args.path = args.path or settings.root
    path = Path(args.path).expanduser().resolve()
    if not path.is_dir():
        parser.error(f"not a directory: {args.path}")

    root, directories = scan.named_by(path)
    if not directories:
        print(f"No repositories under {root}")
        return 0
    # repo-list only checks, so nothing it wires is ever announced.
    pinned = set().union(*(dependencies.pinned(d.path) for d in directories))
    offering = dependencies.offering(d.path for d in directories)
    providers = ecosystems.providers(
        (d.path for d in directories), chosen, settings, pinned, offering
    )
    active = plugins.built_in(
        chosen,
        settings,
        pinned,
        offering,
        providers,
        outcome.starting,
        upgrade_locks=False,
        own_go_modules=[],
    )
    scan.survey(directories, active, fetch_first=args.fetch)
    ask_integration.ask_unset(directories, root, active)
    return report.show(root, directories, clean_too=args.all)


if __name__ == "__main__":
    raise SystemExit(main())
