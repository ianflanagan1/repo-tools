"""packagist publish <dir>

Submits a PHP Composer package that is already on GitHub to Packagist, and adds the GitHub
webhook that keeps Packagist up to date. Each step is skipped when already done, so it is safe
to re-run after a failure.

    1. Submit the package to Packagist
    2. Add the GitHub webhook that tells Packagist about new pushes and tags

The package's origin remote must be a public GitHub repo (run `github publish` first).
"""

import json
import sys
from pathlib import Path

from cli_kit import cli, outcome
from cli_kit.outcome import Done, NothingToDo, Precondition
from cli_kit.proc import output

from repo_tools import clone
from repo_tools.github import api as github
from repo_tools.packagist import api as packagist


def register(subparsers: cli.Subparsers) -> None:
    parser = subparsers.add_parser(
        "publish",
        help="submit the package and add the update webhook",
        description=__doc__.split("\n\n", 1)[1],
    )
    parser.add_argument("dir", type=Path)
    parser.set_defaults(run=lambda args: publish(args.dir))


def publish(directory: Path) -> Done | NothingToDo:
    if not directory.is_dir():
        raise Precondition(f"No such directory: {directory}.")
    directory = directory.resolve()
    package = package_name(directory)

    origin = clone.origin_url(directory)
    if origin is None:
        raise Precondition("No origin remote.", "Run `github publish` first.")
    repo = github.repo_from_url(origin)
    visibility = github.visibility(repo)
    if visibility != "public":
        raise Precondition(f"{repo} is {visibility}; Packagist needs a public repo.")

    git = ("git", "-C", str(directory))
    if not output(*git, "tag"):
        branch = output(*git, "branch", "--show-current")
        print(f"Packagist: no tags yet, so only dev-{branch} will be installable", file=sys.stderr)

    # 1. Package
    if not packagist.package_exists(package):
        packagist.submit(f"https://github.com/{repo}")
        outcome.changed(f"Submitted {package}")

    # 2. Webhook
    if not any("packagist.org" in url for url in github.hook_urls(repo)):
        github.add_hook(repo, *packagist.github_hook())
        outcome.changed("Added the Packagist webhook")

    url = packagist.package_url(package)
    if not outcome.changes():
        return NothingToDo(f"Already published: {url}")
    return Done("Published.", url)


def package_name(directory: Path) -> str:
    """The package name from the directory's composer.json."""
    try:
        composer = json.loads((directory / "composer.json").read_text())
    except FileNotFoundError:
        raise Precondition(f"No composer.json in {directory}.") from None
    except ValueError as error:
        raise Precondition("composer.json is not valid JSON.", str(error)) from None
    name = composer.get("name") if isinstance(composer, dict) else None
    if not isinstance(name, str) or not name:
        raise Precondition("composer.json has no name.")
    return name
