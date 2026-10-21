"""github publish [dir] [repo-name] [--private] [--no-ci-wait]

Publishes a git repository directory to GitHub, under the account gh is logged in as. Each step
is skipped when already done, so it is safe to re-run after a failure.

    1. Create the GitHub repo
    2. Add it as the origin remote
    3. Push the current branch and all tags
    4. Wait for the CI run on the pushed commit, when the repo has a workflow, unless
       --no-ci-wait is given

dir defaults to the current directory, and repo-name to the directory's name. The repo is public
unless --private is given. Its description comes from the project's package manifest when it has
one (see repo_tools.manifest). An existing repo is never edited: if its visibility differs
from the one asked for, the command stops.
"""

import subprocess
import time
from pathlib import Path

from cli_kit import cli, outcome
from cli_kit.outcome import Done, Failure, NothingToDo, Precondition
from cli_kit.proc import output, run, succeeds

from repo_tools import clone, manifest
from repo_tools.github import api

CI_START_ATTEMPTS = 20
CI_START_INTERVAL = 3  # seconds
FAILED_LOG_LINES = 50


def register(subparsers: cli.Subparsers) -> None:
    parser = subparsers.add_parser(
        "publish",
        help="create the repo, push, and wait for CI",
        description=__doc__.split("\n\n", 1)[1],
    )
    parser.add_argument("dir", nargs="?", type=Path, default=Path("."))
    parser.add_argument("name", nargs="?", metavar="repo-name")
    parser.add_argument("--private", action="store_true", help="create the repo as private")
    parser.add_argument(
        "--no-ci-wait", action="store_true", help="don't wait for the CI run on the pushed commit"
    )
    parser.set_defaults(
        run=lambda args: publish(
            args.dir,
            "private" if args.private else "public",
            args.name,
            wait_for_ci=not args.no_ci_wait,
        )
    )


def publish(
    directory: Path, visibility: str, name: str | None, wait_for_ci: bool = True
) -> Done | NothingToDo:
    if not directory.is_dir():
        raise Precondition(f"No such directory: {directory}.")
    directory = directory.resolve()

    git = ("git", "-C", str(directory))
    if not succeeds(*git, "rev-parse", "--is-inside-work-tree"):
        raise Precondition(f"{directory} is not a git repository.")
    if output(*git, "status", "--porcelain"):
        raise Precondition(f"Uncommitted changes in {directory}.")
    branch = output(*git, "branch", "--show-current")
    if not branch:
        raise Precondition(f"HEAD is detached in {directory}.")

    repo = f"{api.current_user()}/{name or directory.name}"
    url = f"https://github.com/{repo}"
    origin = clone.origin_url(directory)
    if origin is not None and api.repo_from_url(origin) != repo:
        raise Precondition(f"origin is {origin}, not {repo}.")

    # 1. Repo
    if api.exists(repo):
        actual = api.visibility(repo)
        if actual != visibility:
            raise Precondition(f"{repo} already exists and is {actual}, not {visibility}.")
    else:
        api.create(repo, visibility, manifest.description(directory))
        outcome.changed(f"Created {repo} ({visibility})")

    # 2. Remote
    if origin is None:
        run(*git, "remote", "add", "origin", f"git@github.com:{repo}.git")
        outcome.changed(f"Added origin {repo}")

    # 3. Push
    if clone.push(*git, "push", "--porcelain", "-u", "origin", branch):
        outcome.changed(f"Pushed {branch}")
    if clone.push(*git, "push", "--porcelain", "origin", "--tags"):
        outcome.changed("Pushed tags")

    # 4. CI
    workflows = directory / ".github" / "workflows"
    ci = wait_for_ci and (any(workflows.glob("*.yml")) or any(workflows.glob("*.yaml")))
    if ci:
        _wait_for_ci(repo, output(*git, "rev-parse", "HEAD"))

    if not outcome.changes():
        return NothingToDo(f"Already published: {url}")
    return Done("Published.", url, *(["CI passed."] if ci else []))


def _wait_for_ci(repo: str, commit: str) -> None:
    list_runs = ("gh", "run", "list", "--repo", repo, "--commit", commit, "--limit", "1")
    run_id = ""
    for _ in range(CI_START_ATTEMPTS):
        run_id = output(*list_runs, "--json", "databaseId", "--jq", ".[0].databaseId // empty")
        if run_id:
            break
        time.sleep(CI_START_INTERVAL)
    if not run_id:
        raise Failure(f"No CI run started for {commit}.")

    watch = ("gh", "run", "watch", run_id, "--repo", repo, "--exit-status")
    if subprocess.run(watch, stdout=subprocess.DEVNULL, check=False).returncode == 0:
        return
    log = subprocess.run(
        ("gh", "run", "view", run_id, "--repo", repo, "--log-failed"),
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    raise Failure(
        f"CI failed: https://github.com/{repo}/actions/runs/{run_id}",
        *log.splitlines()[-FAILED_LOG_LINES:],
    )
