"""Fix what repo-list reports, in one repository or in every one under a directory.

path is a repository, or a directory to search as repo-list does (default: root in config.toml,
or ~/projects).
Every repository is fetched first, once for all of its worktrees. Then each is fixed, a
repository's worktrees one after another, the one that updates its trunk first, so the others
catch up with the trunk as it now is. In each:

  📝 uncommitted files   committed by Claude Code's /ianf-commit skill, then checked: the work tree
                         must be clean, on the same branch or detached HEAD, with earlier
                         commits untouched; never on the trunk in the PR modes
  🔌 no remote           published with `github publish`, public
  📥 behind              fast-forwarded to the upstream; in local mode, a trunk checked out
                         here with commits of its own has them rebased onto it
  🔄 behind its base     rebased onto it, or in pr-merge mode the base merged in
  📤 unpushed            pushed to the upstream, or with no upstream to the only remote
  🔃 no pull request     opened as a draft, in the PR modes
  📁 not a repository    with --init only: initialised, committed and published
  🐘 Packagist           with --packagist only, for a package of your vendor's, once pushed:
                         `packagist publish`, then `packagist update`, which waits until
                         Packagist has what was pushed
  🟥 npm                 with --npm only, for a package of your scope's, once pushed: a
                         package not on npm is published with `npmjs publish`, which asks for
                         one-time passwords; then `npmjs wait` waits until npm has every
                         version tag, which the package's publish workflow publishes

Nothing is forced, except a branch rebased in pr-rebase mode, pushed with a lease. A branch both
behind and unpushed has diverged, and is left alone, but for the trunk in local mode; so are
stashes, and HEAD when catching up would conflict. A rebase or merge that stops at a conflict is
undone. A repository whose commit fails is left there, one whose fetch failed is neither pushed
nor pulled, and a directory a Claude Code session is busy in is left alone. Ends with repo-list's
report of what's left.

Exit status: 0 all clean, 1 something still needs attention, 2 usage error.
"""

from pathlib import Path

from cli_kit import cli, devbox
from cli_kit.colour import GREEN, GREY, RED, YELLOW, Style

from repo_list import config, integration, plugins, report, scan
from repo_list.plugin import Plugin, Stage
from repo_list.scan import ConfigInvalid, Directory


def main(argv: list[str] | None = None) -> int:
    parser = cli.ArgumentParser(
        prog="repo-fix",
        description=__doc__,
    )
    parser.add_argument("path", nargs="?", help="default: root in config.toml, or ~/projects")
    parser.add_argument(
        "--init",
        action="store_true",
        help="make each directory of files a repository, and publish it",
    )
    parser.add_argument(
        "--no-ci-wait", action="store_true", help="don't wait for CI after publishing"
    )
    parser.add_argument(
        "-p",
        "--packagist",
        action="store_true",
        help="publish and update each package of your vendor's on Packagist",
    )
    parser.add_argument(
        "--npm",
        action="store_true",
        help="publish each package of your scope's on npm, and wait for its version tags",
    )
    args = parser.parse_args(argv)
    devbox.use_tools()
    settings = config.for_command(parser, args.packagist, args.npm)
    vendor = settings.packagist_vendor if args.packagist else None
    scope = settings.npm_scope if args.npm else None
    args.path = args.path or settings.root
    path = Path(args.path).expanduser().resolve()
    if not path.is_dir():
        parser.error(f"not a directory: {args.path}")

    if directory := scan.classify(path):
        root, directories = path.parent, [directory]
    else:
        root, directories = path, scan.find(path)
    if not directories:
        print(f"No repositories under {root}")
        return 0

    active = plugins.built_in(vendor, scope, init=args.init, wait_for_ci=not args.no_ci_wait)
    scan.survey(directories, active, fetch_first=True)
    colour = Style.for_stream()
    fixed_any = False
    changed: set[Path] = set()
    for directory in in_fix_order(directories):
        log = Log(directory.path.relative_to(root), colour)
        common = directory.place.common_dir if directory.place else None
        if common in changed:
            # An earlier worktree's fix may have moved the trunk this one catches up with.
            scan.check_all(directory, active)
        if directory.config_error:
            log(False, ConfigInvalid(directory.config_error).describe())
        elif directory.place and directory.place.claude_working:
            if directory.problems:
                log(False, "Left alone: a Claude Code session is working here")
        else:
            fix(directory, active, log)
        if common and log.started:
            changed.add(common)
        if directory.trunk_update_failed:
            for other in directories:
                if other.place and other.place.common_dir == common:
                    other.trunk_stale = True
        fixed_any = fixed_any or log.started
    if fixed_any:
        print()
    scan.survey(directories, active, fetch_first=True)
    return report.show(root, directories)


def in_fix_order(directories: list[Directory]) -> list[Directory]:
    """The directories in the order to fix them: each repository's worktrees together, the one that
    updates its trunk first, so the others catch up with the trunk as it now is."""
    described = [
        (i, f.place.common_dir, f.place.head, f.place.is_main)
        if f.place
        else (i, None, None, False)
        for i, f in enumerate(directories)
    ]
    trunks = {f.place.common_dir: f.place.trunk for f in directories if f.place}
    return [directories[i] for i in integration.fix_order(described, trunks)]


class Log:
    """Prints what was done to one directory, under its path, which is printed only if needed.

    On a terminal it is coloured as repo-list colours its report: what failed in yellow, and the
    details quoted under it in grey.
    """

    def __init__(self, path: Path, colour: Style) -> None:
        self.path = path
        self.colour = colour
        self.started = False

    def __call__(self, ok: bool, line: str, *details: str) -> None:
        colour = self.colour
        if not self.started:
            print(report.name(self.path, colour))
            self.started = True
        line += ":" if details else ""
        mark = colour(GREEN, "✔") if ok else colour(RED, "✘")
        print(f"  {mark} {line if ok else colour(YELLOW, line)}")
        for detail in details:
            print(f"    {colour(GREY, detail)}")


def fix(directory: Directory, active: list[Plugin], log: Log) -> None:
    """Runs the fix of each plugin that found something in the directory, stage by stage.

    Once a fix has run, each later plugin checks the directory again before its fix, as the fix may
    have changed what it finds: a commit leaves commits to push. A fix that fails stops the
    directory there, and a directory git couldn't read is left alone.
    """
    changed = False
    for stage in Stage:
        for plugin in (p for p in active if p.stage is stage):
            if directory.git_failed or (changed and not scan.check(directory, plugin)):
                return
            problems = directory.found.get(plugin.name)
            if not problems:
                continue
            if not plugin.fix(directory, problems, log):
                return
            changed = True


if __name__ == "__main__":
    raise SystemExit(main())
