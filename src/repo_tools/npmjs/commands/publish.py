"""npmjs publish <dir>

Puts an npm package that is already on GitHub onto npm, and trusts its GitHub Actions
workflow .github/workflows/publish.yml to publish each version tag from then on. Each step is
skipped when already done, so it is safe to re-run after a failure.

    1. Publish the package from this clone, as the version tag at HEAD, when npm doesn't have
       it yet: npm can't trust a workflow to publish a package that doesn't exist
    2. Trust the publish workflow to publish the package

The package's origin remote must be a public GitHub repo (run `github publish` first), and
package.json must name it as its repository. A new package needs a version tag at HEAD and no
uncommitted changes (run `github release` first). npm runs from the package's devbox, logged
in as you there, and asks for a one-time password.
"""

import json
from pathlib import Path

from cli_kit import cli, outcome
from cli_kit.outcome import Done, NothingToDo, Precondition
from cli_kit.proc import output

from repo_tools import clone, versions
from repo_tools.github import api as github
from repo_tools.npmjs import api as npm


def register(subparsers: cli.Subparsers) -> None:
    parser = subparsers.add_parser(
        "publish",
        help="publish the package's first version and trust its publish workflow",
        description=__doc__.split("\n\n", 1)[1],
    )
    parser.add_argument("dir", type=Path)
    parser.set_defaults(run=lambda args: publish(args.dir))


def publish(directory: Path) -> Done | NothingToDo:
    if not directory.is_dir():
        raise Precondition(f"No such directory: {directory}.")
    directory = directory.resolve()
    package = package_name(directory)
    if not (directory / "devbox.json").is_file():
        raise Precondition(
            f"No devbox.json in {directory}.", "npm runs from the package's devbox, with nodejs."
        )
    if not (directory / ".github" / "workflows" / npm.WORKFLOW).is_file():
        raise Precondition(
            f"No .github/workflows/{npm.WORKFLOW} in {directory}.",
            "It's the workflow npm will trust to publish each version tag.",
        )

    origin = clone.origin_url(directory)
    if origin is None:
        raise Precondition("No origin remote.", "Run `github publish` first.")
    repo = github.repo_from_url(origin)
    declared = repository(directory)
    if declared.lower() != repo.lower():
        raise Precondition(f"package.json names {declared}, but origin is {repo}.")
    visibility = github.visibility(repo)
    if visibility != "public":
        raise Precondition(f"{repo} is {visibility}; npm provenance needs a public repo.")
    user = npm.logged_in_as(directory)
    if user is None:
        raise Precondition(
            "Not logged in to npm.", f"Run `devbox run -- npm login` in {directory}."
        )
    if not npm.has_two_factor(directory):
        raise Precondition(
            "Two-factor authentication is off for your npm account.",
            "npm needs it to publish and to trust a workflow.",
            f"Turn it on for authorization and writes at https://www.npmjs.com/settings/{user}/tfa,",
            "then run `npmjs publish` again.",
        )

    published = npm.versions(package)
    tag = tagged_version(directory) if published is None else None

    # 1. First version
    if tag is not None:
        version = tag.removeprefix("v")
        npm.publish(directory, version)
        outcome.changed(f"Published {package}@{version}")

    # 2. Trust
    configs = npm.trusts(directory, package)
    if not npm.trusts_workflow(configs, repo):
        if configs:
            raise Precondition(
                f"npm already trusts another publisher for {package}.",
                f"To replace it: npm trust revoke {package} --id={configs[0].get('id')}",
                "Then run `npmjs publish` again.",
            )
        npm.trust(directory, package, repo)
        outcome.changed(f"Trusted {repo}'s {npm.WORKFLOW} to publish {package}")

    url = npm.package_url(package)
    if not outcome.changes():
        return NothingToDo(f"Already published: {url}")
    return Done("Published.", url)


def tagged_version(directory: Path) -> str:
    """The highest version tag at HEAD, for a package npm doesn't have yet. The tree must be
    clean, so what's published is what's tagged."""
    git = ("git", "-C", str(directory))
    if output(*git, "status", "--porcelain"):
        raise Precondition(
            f"Uncommitted changes in {directory}.",
            "Its first version is published from this clone, so it must be what's tagged.",
        )
    tags = [t for t in output(*git, "tag", "--points-at", "HEAD").split() if versions.is_version(t)]
    if not tags:
        raise Precondition(
            "The package isn't on npm yet, and HEAD has no version tag.",
            f"Run `github release {directory} minor` first; its tag is the version published.",
        )
    return max(tags, key=versions.key)


def package_name(directory: Path) -> str:
    """The package name from the directory's package.json, which mustn't be private."""
    manifest = _package_json(directory)
    name = manifest.get("name")
    if not isinstance(name, str) or not name:
        raise Precondition("package.json has no name.")
    if manifest.get("private") is True:
        raise Precondition(f"{name} is private in package.json, so npm won't publish it.")
    return name


def repository(directory: Path) -> str:
    """The owner/name of the GitHub repo the directory's package.json names."""
    field = _package_json(directory).get("repository")
    url = field.get("url") if isinstance(field, dict) else field
    if not isinstance(url, str) or not url:
        raise Precondition(
            "package.json names no repository.",
            "npm provenance needs repository.url to be the GitHub repo.",
        )
    return github.repo_from_url(url.removesuffix("/"))


def _package_json(directory: Path) -> dict:
    try:
        manifest = json.loads((directory / "package.json").read_text())
    except FileNotFoundError:
        raise Precondition(f"No package.json in {directory}.") from None
    except ValueError as error:
        raise Precondition("package.json is not valid JSON.", str(error)) from None
    return manifest if isinstance(manifest, dict) else {}
