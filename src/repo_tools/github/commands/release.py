"""github release <dir> <patch|minor|major>

Releases HEAD of a clone as the next version, which Packagist and other registries that read
git tags then offer. Each step is skipped when already done, so it is safe to re-run after a
failure; a HEAD that already has a version tag is released as that version, whatever level is
given, so no commit gets two.

    1. Tag HEAD with the highest version tag, bumped at the given level. A project with no
       version tags starts from 0.0.0. The tag keeps the highest tag's style, with or without
       a leading v, and is v-style for the first.
    2. Push the tag
    3. Create the GitHub release, with notes GitHub generates from the commits

Only tags of the form [v]MAJOR.MINOR.PATCH count; pre-releases such as v2.0.0-beta1 don't.
Origin's tags are fetched first, so one pushed from elsewhere counts. HEAD must be on origin
already, so the release is of what's on GitHub. An existing tag is never moved.
"""

from pathlib import Path

from cli_kit import cli, outcome
from cli_kit.outcome import Done, NothingToDo, Precondition
from cli_kit.proc import output, succeeds

from repo_tools import clone, versions
from repo_tools.github import api


def register(subparsers: cli.Subparsers) -> None:
    parser = subparsers.add_parser(
        "release",
        help="tag HEAD as the next version, push it, and create the GitHub release",
        description=__doc__.split("\n\n", 1)[1],
    )
    parser.add_argument("dir", type=Path)
    parser.add_argument("level", choices=versions.LEVELS)
    parser.set_defaults(run=lambda args: release(args.dir, args.level))


def release(directory: Path, level: str) -> Done | NothingToDo:
    if not directory.is_dir():
        raise Precondition(f"No such directory: {directory}.")
    directory = directory.resolve()
    git = ("git", "-C", str(directory))
    if not succeeds(*git, "rev-parse", "--is-inside-work-tree"):
        raise Precondition(f"{directory} is not a git repository.")
    if output(*git, "status", "--porcelain"):
        raise Precondition(f"Uncommitted changes in {directory}.")
    if not output(*git, "branch", "--show-current"):
        raise Precondition(f"HEAD is detached in {directory}.")
    origin = clone.origin_url(directory)
    if origin is None:
        raise Precondition("No origin remote.", "Run `github publish` first.")
    repo = api.repo_from_url(origin)

    output(*git, "fetch", "--quiet", "--tags", "origin")
    if output(*git, "rev-list", "--count", "HEAD", "--not", "--remotes=origin") != "0":
        raise Precondition(
            "HEAD isn't on origin.", "Push it first, so the release is of what's on GitHub."
        )

    # 1. Tag
    released = [
        t for t in output(*git, "tag", "--points-at", "HEAD").splitlines() if versions.is_version(t)
    ]
    if released:
        tag = max(released, key=versions.key)
    else:
        tag = versions.next_version(output(*git, "tag").splitlines(), level)
        output(*git, "tag", "--annotate", "--message", tag, tag)
        outcome.changed(f"Tagged HEAD as {tag}")

    # 2. Push
    if clone.push(*git, "push", "--porcelain", "origin", f"refs/tags/{tag}"):
        outcome.changed(f"Pushed {tag}")

    # 3. GitHub release
    if not api.release_exists(repo, tag):
        api.create_release(repo, tag)
        outcome.changed(f"Created the GitHub release {tag}")

    if not outcome.changes():
        return NothingToDo(f"HEAD is already released as {tag}.")
    return Done(f"Released {tag}.", f"https://github.com/{repo}/releases/tag/{tag}")
