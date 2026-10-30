"""Fix what repo-list reports, in one repository or in every one under a directory.

path is a repository, or a directory to search as repo-list does (default: root in config.toml,
or ~/projects).
Every repository is fetched first, once for all of its worktrees, and one that sets no
integration is asked for one, as repo-list asks. Then each is fixed, a
repository's worktrees one after another, the one that updates its trunk first, so the others
catch up with the trunk as it now is. Repositories go in name order, but each that another pins
as a dependency, such as from git in its uv.lock or from Packagist in its composer.lock, goes
before it, and its own pinned dependencies before that; one read from a path doesn't count. So a
dependant's uv.lock can upgrade to what its dependencies just pushed. Repositories that depend on
each other are said to, and go in name order. A dependant is fixed even when its dependency's fix
failed. In each:

  📝 uncommitted files   committed by Claude Code's /ianf-commit skill, then checked: the work tree
                         must be clean, on the same branch or detached HEAD, with earlier
                         commits untouched; never on the trunk with PR integration
  🔌 no remote           published with `github publish`, public
  📥 behind              fast-forwarded to the upstream; with direct integration, a trunk checked
                         out here with commits of its own has them rebased onto it
  🔄 behind its base     rebased onto it, or with pr-merge integration the base merged in
  📤 unpushed            pushed to the upstream, or with no upstream to the only remote
  🔃 no pull request     opened as a draft, with PR integration
  📌 uv.lock             one that `uv lock --upgrade` would change, on the trunk with direct
                         integration: upgraded in the project's devbox, committed alone and pushed
  🔗 lock file behind    with a package flag, on the trunk with direct integration, one holding a
                         package of yours from another repository here at less than its latest:
                         just that package upgraded with composer, npm or uv in the project's
                         devbox, then the lock file committed alone and pushed
  🔖 unreleased commits  with a package flag, for a Composer or npm package of yours, on the
                         trunk with direct integration, once pushed: commits since its latest
                         version tag that change more than lock files, or a package never
                         released, are released as the next patch version with `github release`
                         or `bitbucket release`
  📁 not a repository    with --init only: initialised, committed and published
  🐘 Packagist           with --packagist only, for a package of your vendor's, once released:
                         `packagist publish`, then `packagist update`, which waits until
                         Packagist has what was pushed
  🔴 npm                 with --npm only, for a package of your scope's, once released: a
                         package not on npm is published with `npmjs publish`, which asks for
                         one-time passwords; then `npmjs wait` waits until npm has every
                         version tag, which the package's publish workflow publishes

Nothing is forced, except a branch rebased with pr-rebase integration, pushed with a lease. A
branch both behind and unpushed has diverged, and is left alone, but for the trunk with direct
integration; so are stashes. Any rebase or merge that stops at a conflict is undone, which
is what becomes of HEAD's catching up when it's expected to conflict. A repository whose commit
fails is left there, one whose fetch failed is neither pushed nor pulled, and a directory a
Claude Code session is busy in is left alone, as is one whose .config/ianf-repo-tools.toml sets
skip-fix = true. Ends with repo-list's report of what's left.

Exit status: 0 all clean, 1 something still needs attention, 2 usage error.
"""

import sys
from pathlib import Path

from cli_kit import cli, devbox, outcome
from cli_kit.colour import GREEN, GREY, RED, YELLOW, Style

from repo_list import ask_integration, dependencies, ecosystems, integration, plugins, report, scan
from repo_list.plugin import Plugin, Stage
from repo_list.scan import ConfigInvalid, Directory
from repo_tools import packages


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
    ecosystems.add_flags(
        parser,
        lambda e: (
            f"release and publish {ecosystems.packages_of(e)}, "
            "and upgrade it in the projects here that pin it"
        ),
        "do so for every kind of package, as each flag above does",
    )
    args = parser.parse_args(argv)
    devbox.use_tools()
    chosen = ecosystems.chosen(args)
    settings = ecosystems.settings_for(parser, chosen)
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

    log = Log(Style.for_stream())
    pinned = {d.path: packages.pinned(d.path) for d in directories}
    every_pinned = set().union(*pinned.values())
    active = plugins.built_in(
        chosen,
        settings,
        every_pinned,
        ecosystems.providers((d.path for d in directories), chosen, settings, every_pinned),
        log.begin,
        upgrade_locks=True,
        init=args.init,
        wait_for_ci=not args.no_ci_wait,
    )
    scan.survey(directories, active, fetch_first=True)
    ask_integration.ask_unset(directories, root, active)
    fixed_any = False
    changed: set[Path] = set()
    fixed_names: set[packages.Name] = set()
    order, cycles = in_fix_order(directories, pinned)
    for cycle in cycles:
        names = ", ".join(str(d.path.relative_to(root)) for d in cycle)
        print(f"These depend on each other, so are fixed in name order: {names}")
    for directory in order:
        log.enter(directory.path.relative_to(root))
        common = directory.place.common_dir if directory.place else None
        if common in changed or pinned[directory.path] & fixed_names:
            # An earlier worktree's fix may have moved the trunk this one catches up with, and a
            # dependency's may have pushed what this one's lock file can upgrade to.
            scan.check_all(directory, active)
        if directory.config_error:
            log(False, ConfigInvalid(directory.config_error).describe())
        elif directory.place and directory.place.skip_fix:
            if directory.problems:
                log(False, f"Left alone: skip-fix is set in {scan.SETTINGS}")
        elif directory.place and directory.place.claude_working:
            if directory.problems:
                log(False, "Left alone: a Claude Code session is working here")
        else:
            fix(directory, active, log)
        if common and log.started:
            changed.add(common)
        if log.started:
            fixed_names |= packages.names(directory.path)
        if directory.trunk_update_failed:
            for other in directories:
                if other.place and other.place.common_dir == common:
                    other.trunk_stale = True
        fixed_any = fixed_any or log.started
    if fixed_any:
        print()
    scan.survey(directories, active, fetch_first=True)
    ask_integration.ask_unset(directories, root, active)
    return report.show(root, directories)


def in_fix_order(
    directories: list[Directory], pinned: dict[Path, set[packages.Name]]
) -> tuple[list[Directory], list[list[Directory]]]:
    """The directories in the order to fix them, given what each pins: each repository's worktrees
    together, the one that updates its trunk first, so the others catch up with the trunk as it now
    is, and each repository after those it pins. Then the first directory of each set of
    repositories that pin each other."""
    described = [
        (i, f.place.common_dir, f.place.head, f.place.is_main)
        if f.place
        else (i, None, None, False)
        for i, f in enumerate(directories)
    ]
    trunks = {f.place.common_dir: f.place.trunk for f in directories if f.place}
    repos: dict[Path, list[Directory]] = {}
    for i in integration.fix_order(described, trunks):
        directory = directories[i]
        repos.setdefault(_repo(directory), []).append(directory)
    called = {r: set().union(*(packages.names(d.path) for d in ds)) for r, ds in repos.items()}
    pins = {r: set().union(*(pinned[d.path] for d in ds)) for r, ds in repos.items()}
    order = dependencies.fix_first(list(repos), dependencies.edges(called, pins))
    return (
        [directory for repo in order.keys for directory in repos[repo]],
        [[repos[repo][0] for repo in cycle] for cycle in order.cycles],
    )


def _repo(directory: Directory) -> Path:
    """What the directory's worktrees share: its common git directory, or for a directory git
    can't read, its own path."""
    return directory.place.common_dir if directory.place else directory.path


class Log:
    """Prints what was done to each directory in turn, under its path, which is printed only if
    something is.

    On a terminal it is coloured as repo-list colours its report: what failed in yellow, and the
    details quoted under it in grey. A step starting is grey too, marked as cli-kit marks one.
    One Log serves the whole run, so that what's wired once, such as the agent that commits, can
    announce itself under whichever directory it's working in.
    """

    def __init__(self, colour: Style) -> None:
        self.colour = colour
        self.path = Path()
        self.started = False

    def enter(self, path: Path) -> None:
        """Goes on to the directory at path, from the root."""
        self.path = path
        self.started = False

    def __call__(self, ok: bool, line: str, *details: str) -> None:
        colour = self.colour
        self._header()
        line += ":" if details else ""
        mark = colour(GREEN, "✔") if ok else colour(RED, "✘")
        print(f"  {mark} {line if ok else colour(YELLOW, line)}")
        for detail in details:
            print(f"    {colour(GREY, detail)}")
        sys.stdout.flush()

    def begin(self, line: str) -> None:
        self._header()
        print(f"  {self.colour(GREY, f'{outcome.STARTING} {line}')}", flush=True)

    def _header(self) -> None:
        if not self.started:
            print(report.name(self.path, self.colour))
            self.started = True


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
