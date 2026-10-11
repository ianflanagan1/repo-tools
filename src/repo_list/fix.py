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

import json
import subprocess
import sys
from pathlib import Path

from cli_kit import cli

from repo_list import config, report, scan
from repo_list.scan import (
    Behind,
    FetchFailed,
    Folder,
    GitFailed,
    NoRemote,
    NotARepo,
    PackagistFailed,
    Uncommitted,
    Unpushed,
)

CLAUDE = "claude"
GITHUB = str(Path(sys.prefix) / "bin" / "github")
PACKAGIST = str(Path(sys.prefix) / "bin" / "packagist")
COMMIT_SKILL = "~/.claude/skills/commit"
COMMIT_TIMEOUT_SECONDS = 30 * 60

# The marker git leaves in the git directory during each operation /commit must not interrupt.
IN_PROGRESS = {
    "MERGE_HEAD": "a merge",
    "rebase-merge": "a rebase",
    "rebase-apply": "a rebase",
    "CHERRY_PICK_HEAD": "a cherry-pick",
    "REVERT_HEAD": "a revert",
}


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

    scan.survey(folders, fetch_first=True, packagist_vendor=vendor)
    fixed_any = False
    for folder in folders:
        log = Log(str(folder.path.relative_to(root)))
        fix(folder, log, init=args.init, wait_for_ci=not args.no_ci_wait, packagist_vendor=vendor)
        fixed_any = fixed_any or log.started
    if fixed_any:
        print()
    scan.survey(folders, fetch_first=True, packagist_vendor=vendor)
    return report.show(root, folders)


class Log:
    """Prints what was done to one folder, under its name, which is printed only if needed."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.started = False

    def __call__(self, ok: bool, line: str, *details: str) -> None:
        if not self.started:
            print(self.name)
            self.started = True
        print(f"  {'✔' if ok else '✘'} {line}{':' if details else ''}")
        for detail in details:
            print(f"    {detail}")


def fix(
    folder: Folder, log: Log, init: bool, wait_for_ci: bool, packagist_vendor: str | None
) -> None:
    """Fixes what it can of the folder's problems, as found by scan.survey, in order: make it a
    repository, commit, publish, bring each branch level with its upstream, then bring Packagist
    level with what was pushed, if packagist_vendor is given and it is a package of theirs."""
    repo = folder.path
    problems = folder.problems
    if NotARepo() in problems:
        if not init:
            return
        git(repo, "init", "-q")
        folder.is_repo = True
        log(True, "Initialised a git repository")
        problems = scan.check(repo)
    if GitFailed() in problems:
        return

    if any(isinstance(p, Uncommitted) for p in problems):
        if not commit(repo, log):
            return
        problems = scan.check(repo)

    if NoRemote() in problems:
        if not publish(repo, log, wait_for_ci):
            return
        problems = scan.check(repo)

    if FetchFailed() in folder.problems:
        # Without a fetch, what's behind or unpushed isn't known.
        return
    behind = {p.branch for p in problems if isinstance(p, Behind)}
    unpushed = {p.branch for p in problems if isinstance(p, Unpushed)}
    for branch in sorted(behind | unpushed):
        upstream = git(repo, "rev-parse", "--abbrev-ref", f"{branch}@{{u}}", check=False)
        if branch in behind and branch in unpushed:
            log(False, f"Not syncing {branch}: it has diverged from {upstream}")
        elif branch in behind:
            fast_forward(repo, branch, upstream, log)
        else:
            push(repo, branch, upstream, log)

    # Checked again now, as whatever was just pushed is new to Packagist.
    if not packagist_vendor or scan.check_packagist(repo, packagist_vendor) in (
        [],
        [PackagistFailed()],
    ):
        return
    for command, done in (
        ("publish", "Published on Packagist"),
        ("update", "Updated on Packagist"),
    ):
        if not packagist(command, repo, done, log):
            return


def commit(repo: Path, log: Log) -> bool:
    """Commits all the work with /commit, and checks the result. Says whether it all went in."""
    for marker, operation in IN_PROGRESS.items():
        if (repo / git(repo, "rev-parse", "--git-path", marker)).exists():
            log(False, f"Not committing: {operation} is in progress")
            return False
    branch = git(repo, "symbolic-ref", "-q", "--short", "HEAD", check=False)
    if not branch:
        log(False, "Not committing: HEAD is detached")
        return False
    skill = Path(COMMIT_SKILL).expanduser()
    if not (skill / "SKILL.md").is_file():
        log(False, f"Not committing: no commit skill in {skill}")
        return False

    start = git(repo, "rev-parse", "-q", "--verify", "HEAD", check=False)
    try:
        said = claude_commit(repo, skill)
    except subprocess.TimeoutExpired:
        log(False, f"Commit failed: claude took over {COMMIT_TIMEOUT_SECONDS // 60} minutes")
        return False

    # Judge the run by git's state, not by what claude says: a skill that fails to load still
    # ends as a success, with nothing done.
    now_on = git(repo, "symbolic-ref", "-q", "--short", "HEAD", check=False)
    if now_on != branch:
        log(False, f"Commit failed: it left {branch} for {now_on or 'a detached HEAD'}")
        return False
    head = git(repo, "rev-parse", "-q", "--verify", "HEAD", check=False)
    if start and head != start and not is_ancestor(repo, start, head):
        short = git(repo, "rev-parse", "--short", start)
        log(False, f"Commit failed: it rewrote commits made before it; the branch was at {short}")
        return False
    if head and head != start:
        revisions = f"{start}..{head}" if start else head
        for line in git(repo, "log", "--reverse", "--format=%h %s", revisions).splitlines():
            log(True, f"Committed {line}")
    if git(repo, "status", "--porcelain"):
        failed = "Commit left work uncommitted" if head != start else "Commit failed"
        log(False, failed, *said.splitlines())
        return False
    return True


def claude_commit(repo: Path, skill: Path) -> str:
    """Runs /commit in repo, headless, and returns what claude said.

    The skill's files may be symlinks to elsewhere, and claude lets the skill read only files
    in its working directories, so every directory they lead to is added.
    """
    allowed = {skill.resolve()} | {
        p.resolve() if p.is_dir() else p.resolve().parent for p in skill.rglob("*")
    }
    result = subprocess.run(
        [
            CLAUDE,
            "-p",
            "/commit",
            *(arg for directory in sorted(allowed) for arg in ("--add-dir", str(directory))),
            "--output-format",
            "json",
            "--no-session-persistence",
        ],
        cwd=repo,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=COMMIT_TIMEOUT_SECONDS,
    )
    try:
        return str(json.loads(result.stdout)["result"])
    except (json.JSONDecodeError, KeyError, TypeError):
        return (result.stdout + result.stderr).strip()


def publish(repo: Path, log: Log, wait_for_ci: bool) -> bool:
    """Publishes the repository with github publish. Says whether it worked."""
    command = [GITHUB, "publish", str(repo), *([] if wait_for_ci else ["--no-ci-wait"])]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        log(False, "Publish failed", *(result.stderr + result.stdout).strip().splitlines())
        return False
    # Its status line repeats what this one says.
    details = [line for line in result.stdout.splitlines() if not line.startswith("✅")]
    log(True, "Published", *details)
    return True


def packagist(command: str, repo: Path, done: str, log: Log) -> bool:
    """Runs a packagist command on the repository, and logs it if it changed anything. Says
    whether it worked."""
    result = subprocess.run([PACKAGIST, command, str(repo)], capture_output=True, text=True)
    if result.returncode != 0:
        log(
            False,
            f"Packagist {command} failed",
            *(result.stderr + result.stdout).strip().splitlines(),
        )
        return False
    lines = result.stdout.splitlines()
    if any(line.startswith("✅") for line in lines):
        log(True, done, *(line for line in lines if not line.startswith("✅")))
    return True


def fast_forward(repo: Path, branch: str, upstream: str, log: Log) -> None:
    current = git(repo, "symbolic-ref", "-q", "--short", "HEAD", check=False)
    if branch == current:
        command = ["merge", "-q", "--ff-only", upstream]
    else:
        command = ["fetch", "-q", ".", f"refs/remotes/{upstream}:refs/heads/{branch}"]
    result = run_git(repo, *command)
    if result.returncode == 0:
        log(True, f"Fast-forwarded {branch} to {upstream}")
    else:
        log(False, f"Fast-forward of {branch} failed", *result.stderr.strip().splitlines())


def push(repo: Path, branch: str, upstream: str, log: Log) -> None:
    if upstream:
        remote = git(repo, "config", f"branch.{branch}.remote")
        merge = git(repo, "config", f"branch.{branch}.merge")
        result = run_git(repo, "push", "-q", remote, f"refs/heads/{branch}:{merge}")
        done = f"Pushed {branch} to {remote}"
    else:
        remotes = git(repo, "remote").splitlines()
        if len(remotes) != 1:
            choices = f"{len(remotes)} remotes to choose from"
            log(False, f"Not pushing {branch}: it has no upstream, and {choices}")
            return
        result = run_git(repo, "push", "-q", "-u", remotes[0], branch)
        done = f"Pushed {branch} to {remotes[0]}, now its upstream"
    if result.returncode == 0:
        log(True, done)
    else:
        log(False, f"Push of {branch} failed", *result.stderr.strip().splitlines())


def git(repo: Path, *args: str, check: bool = True) -> str:
    """Runs git in repo and returns its output, stripped; with check=False, "" on failure."""
    result = run_git(repo, *args)
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, result.args, stderr=result.stderr)
    return result.stdout.strip() if result.returncode == 0 else ""


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Runs git in repo, never stopping to ask for a password."""
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, env=scan.batch_env()
    )


def is_ancestor(repo: Path, older: str, newer: str) -> bool:
    return run_git(repo, "merge-base", "--is-ancestor", older, newer).returncode == 0


if __name__ == "__main__":
    raise SystemExit(main())
