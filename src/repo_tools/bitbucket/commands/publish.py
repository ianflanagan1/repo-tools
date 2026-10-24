"""bitbucket publish [dir] [repo-name] [--private] [--project <key>] [--no-ci-wait]

Publishes a git repository directory to Bitbucket, in the workspace set in config.toml unless
repo-name names one, as workspace/name. Each step is skipped when already done, so it is safe to
re-run after a failure.

    1. Create the Bitbucket repo
    2. Add it as the origin remote
    3. Turn Pipelines on, when the directory has a bitbucket-pipelines.yml
    4. Push the current branch and all tags
    5. Wait for the pipeline run on the pushed commit, when Pipelines is on, unless
       --no-ci-wait is given

dir defaults to the current directory, and repo-name to the directory's name; the slug is the
name in lower case. The repo is public unless --private is given, and goes in the workspace's
default project unless --project names one by its key. Its description comes from the
project's package manifest when it has one; otherwise the provider set as description.provider
in config.toml writes one from the tracked files (see repo_tools.description), and it's created
with none when that fails. An existing repo is never edited: if its visibility differs from the
one asked for, the command stops.

Pipelines runs only on pushes made while it's on, which is why it's turned on before pushing.
"""

import time
from pathlib import Path

from cli_kit import cli, outcome
from cli_kit.models import Model
from cli_kit.outcome import Done, Failure, NothingToDo, Precondition
from cli_kit.proc import output, run, succeeds

from repo_tools import clone, description
from repo_tools.bitbucket import api
from repo_tools.bitbucket.forge import Bitbucket

CI_START_ATTEMPTS = 20
CI_START_INTERVAL = 3  # seconds
CI_POLL_INTERVAL = 5  # seconds
CI_TIMEOUT = 60 * 60  # seconds
FAILED_LOG_LINES = 50


def register(subparsers: cli.Subparsers) -> None:
    parser = subparsers.add_parser(
        "publish",
        help="create the repo, push, and wait for Pipelines",
        description=__doc__.split("\n\n", 1)[1],
    )
    parser.add_argument("dir", nargs="?", type=Path, default=Path("."))
    parser.add_argument("name", nargs="?", metavar="repo-name")
    parser.add_argument("--private", action="store_true", help="create the repo as private")
    parser.add_argument("--project", help="the key of the workspace project to create it in")
    parser.add_argument(
        "--no-ci-wait", action="store_true", help="don't wait for the pipeline on the pushed commit"
    )
    parser.set_defaults(
        run=lambda args: publish(
            args.dir,
            private=args.private,
            name=args.name,
            model=description.configured_model(),
            project=args.project,
            wait_for_ci=not args.no_ci_wait,
        )
    )


def publish(
    directory: Path,
    private: bool,
    name: str | None,
    model: Model | None,
    project: str | None = None,
    wait_for_ci: bool = True,
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

    forge = Bitbucket()
    workspace, _, slug = forge.full_name(name or directory.name).rpartition("/")
    repo = f"{workspace}/{slug.lower()}"
    url = api.web_url(repo)
    origin = clone.origin_url(directory)
    if origin is not None and api.repo_from_url(origin).lower() != repo:
        raise Precondition(f"origin is {origin}, not {repo}.")
    client = forge.client

    # 1. Repo
    visibility = "private" if private else "public"
    if (existing := client.repository(repo)) is not None:
        actual = "private" if existing["is_private"] else "public"
        if actual != visibility:
            raise Precondition(f"{repo} already exists and is {actual}, not {visibility}.")
    else:
        text = description.for_new_repo(directory, slug, model, api.DESCRIPTION_MAX_LENGTH)
        client.create(repo, private, text, project)
        outcome.changed(f"Created {repo} ({visibility})")

    # 2. Remote
    if origin is None:
        run(*git, "remote", "add", "origin", api.ssh_url(repo))
        outcome.changed(f"Added origin {repo}")

    # 3. Pipelines
    pipelines = (directory / "bitbucket-pipelines.yml").is_file()
    if pipelines and not client.pipelines_enabled(repo):
        client.enable_pipelines(repo)
        outcome.changed("Turned Pipelines on")

    # 4. Push
    if clone.push(*git, "push", "--porcelain", "-u", "origin", branch):
        outcome.changed(f"Pushed {branch}")
    if clone.push(*git, "push", "--porcelain", "origin", "--tags"):
        outcome.changed("Pushed tags")

    # 5. CI
    ci = wait_for_ci and pipelines
    if ci:
        _wait_for_ci(client, repo, output(*git, "rev-parse", "HEAD"))

    if not outcome.changes():
        return NothingToDo(f"Already published: {url}")
    return Done("Published.", url, *(["Pipeline passed."] if ci else []))


def _wait_for_ci(client: api.Bitbucket, repo: str, commit: str) -> None:
    pipeline = None
    for _ in range(CI_START_ATTEMPTS):
        pipeline = client.pipeline_for(repo, commit)
        if pipeline:
            break
        time.sleep(CI_START_INTERVAL)
    if not pipeline:
        raise Failure(
            f"No pipeline started for {commit}.",
            "Pipelines runs only on pushes made while it's on: push a new commit to start one.",
        )

    url = f"{api.web_url(repo)}/pipelines/results/{pipeline['build_number']}"
    deadline = time.monotonic() + CI_TIMEOUT
    while pipeline["state"]["name"] != "COMPLETED":
        if time.monotonic() > deadline:
            raise Failure(f"The pipeline is still running after an hour: {url}")
        time.sleep(CI_POLL_INTERVAL)
        pipeline = client.pipeline(repo, pipeline["uuid"])

    result = pipeline["state"].get("result", {}).get("name")
    if result == "SUCCESSFUL":
        return
    log = client.failed_step_log(repo, pipeline["uuid"])
    raise Failure(f"The pipeline ended {result}: {url}", *log.splitlines()[-FAILED_LOG_LINES:])
