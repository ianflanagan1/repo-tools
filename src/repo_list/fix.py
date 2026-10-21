"""Fix what repo-list reports, in one repository or in every one under a folder.

path is a repository, or a folder to search as repo-list does (default: root in config.toml,
or ~/projects).
Every repository is fetched first. Then, in each:

  📝 uncommitted files   committed by Claude Code's /commit skill, then checked: the work tree
                         must be clean, on the same branch, with earlier commits untouched
  🔌 no remote           published with `github publish`, public
  📥 behind              fast-forwarded to the upstream
  📤 unpushed            pushed to the upstream, or with no upstream to the only remote
  📁 not a repository    with --init only: initialised, committed and published
  🐘 Packagist           with --packagist only, for a package of your vendor's, once pushed:
                         `packagist publish`, then `packagist update`, which waits until
                         Packagist has what was pushed

Nothing is forced. A branch both behind and unpushed has diverged, and is left alone, as are
stashes and commits on a detached HEAD. A repository whose /commit fails is left there, and one
whose fetch failed is neither pushed nor pulled. Ends with repo-list's report of what's left.

Exit status: 0 all clean, 1 something still needs attention, 2 usage error.
"""

from pathlib import Path

from cli_kit import cli
from cli_kit.colour import GREEN, GREY, RED, YELLOW, Style

from repo_list import config, plugins, report, scan
from repo_list.plugin import Plugin, Stage
from repo_list.scan import Folder


def main(argv: list[str] | None = None) -> int:
    parser = cli.ArgumentParser(
        prog="repo-fix",
        description=__doc__,
    )
    parser.add_argument("path", nargs="?", help="default: root in config.toml, or ~/projects")
    parser.add_argument(
        "--init", action="store_true", help="make each folder of files a repository, and publish it"
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
    args = parser.parse_args(argv)
    settings = config.for_command(parser, args.packagist)
    vendor = settings.packagist_vendor if args.packagist else None
    args.path = args.path or settings.root
    path = Path(args.path).expanduser().resolve()
    if not path.is_dir():
        parser.error(f"not a directory: {args.path}")

    if folder := scan.classify(path):
        root, folders = path.parent, [folder]
    else:
        root, folders = path, scan.find(path)
    if not folders:
        print(f"No repositories under {root}")
        return 0

    active = plugins.built_in(vendor, init=args.init, wait_for_ci=not args.no_ci_wait)
    scan.survey(folders, active, fetch_first=True)
    colour = Style.for_stream()
    fixed_any = False
    for folder in folders:
        log = Log(folder.path.relative_to(root), colour)
        fix(folder, active, log)
        fixed_any = fixed_any or log.started
    if fixed_any:
        print()
    scan.survey(folders, active, fetch_first=True)
    return report.show(root, folders)


class Log:
    """Prints what was done to one folder, under its path, which is printed only if needed.

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


def fix(folder: Folder, active: list[Plugin], log: Log) -> None:
    """Runs the fix of each plugin that found something in the folder, stage by stage.

    Once a fix has run, each later plugin checks the folder again before its fix, as the fix may
    have changed what it finds: a commit leaves commits to push. A fix that fails stops the
    folder there, and a folder git couldn't read is left alone.
    """
    changed = False
    for stage in Stage:
        for plugin in (p for p in active if p.stage is stage):
            if folder.git_failed or (changed and not scan.check(folder, plugin)):
                return
            problems = folder.found.get(plugin.name)
            if not problems:
                continue
            if not plugin.fix(folder, problems, log):
                return
            changed = True


if __name__ == "__main__":
    raise SystemExit(main())
