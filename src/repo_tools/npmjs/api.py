"""npm operations, for the npmjs commands.

npm runs from the package's own devbox, so each project pins its own Node and npm and none is
needed on the PATH. It runs as whoever is logged in to npm there; this never reads a token.
Commands that may ask for a one-time password run with the terminal, so npm can ask.
"""

import json
import os
import pty
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from cli_kit.outcome import Failure
from cli_kit.proc import output

from repo_tools import versions as version_tags

REGISTRY = "https://registry.npmjs.org"
WEBSITE = "https://www.npmjs.com"
WORKFLOW = "publish.yml"
"""The GitHub Actions workflow npm trusts to publish each version tag."""


def package_url(package: str) -> str:
    return f"{WEBSITE}/package/{package}"


def escaped(package: str) -> str:
    """The package name as the registry's URLs have it: a scope's slash is escaped."""
    return package.replace("/", "%2f")


def versions(package: str) -> frozenset[str] | None:
    """The versions npm has of the package, or None when it doesn't have the package."""
    request = urllib.request.Request(
        f"{REGISTRY}/{escaped(package)}",
        headers={"Accept": "application/vnd.npm.install-v1+json", "Cache-Control": "no-cache"},
    )
    try:
        with urllib.request.urlopen(request) as response:
            return frozenset(json.load(response).get("versions", {}))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise Failure(f"npm answered {error.code} when looking up {package}.") from None
    except urllib.error.URLError as error:
        raise Failure("Couldn't reach npm.", str(error.reason)) from None


def logged_in_as(directory: Path) -> str | None:
    """The npm user logged in for the directory's devbox, or None when nobody is."""
    result = subprocess.run([*_npm(directory), "whoami"], capture_output=True, text=True)
    return result.stdout.strip() or None if result.returncode == 0 else None


def has_two_factor(directory: Path) -> bool:
    """Whether the npm account logged in for the directory's devbox has two-factor
    authentication on, which npm needs to publish and to trust a workflow."""
    profile = json.loads(output(*_npm(directory), "profile", "get", "--json"))
    return bool(profile.get("tfa")) if isinstance(profile, dict) else False


def publish(directory: Path, version: str) -> None:
    """Publishes the package in directory, as version, from this machine; npm asks for a
    one-time password. package.json is given the version for the publish and put back after."""
    manifest = directory / "package.json"
    original = manifest.read_text()
    stamped = json.loads(original) | {"version": version}
    manifest.write_text(json.dumps(stamped, indent=2, ensure_ascii=False) + "\n")
    try:
        if subprocess.run([*_npm(directory), "publish", "--access", "public"]).returncode != 0:
            raise Failure("npm publish failed.", "npm's error is above.")
    finally:
        manifest.write_text(original)


def trusts(directory: Path, package: str) -> list[dict]:
    """The package's trusted publishers. npm may ask for a one-time password."""
    status, printed = _in_terminal(
        *_npm(directory), "trust", "list", package, "--json", "--no-progress"
    )
    if status != 0:
        raise Failure("npm trust list failed.")
    return parse_trusts(printed)


def trust(directory: Path, package: str, repo: str) -> None:
    """Trusts the repo's publish workflow to publish the package. npm asks for a one-time
    password."""
    command = [
        *_npm(directory),
        "trust",
        "github",
        package,
        "--file",
        WORKFLOW,
        "--repository",
        repo,
        "--allow-publish",
        "--yes",
    ]
    if subprocess.run(command).returncode != 0:
        raise Failure("npm trust failed.", "npm's error is above.")


def parse_trusts(printed: str) -> list[dict]:
    """The configurations `npm trust list --json` printed: a JSON object for each, among
    whatever else the terminal showed, such as a one-time password prompt."""
    decoder = json.JSONDecoder()
    found = []
    start = printed.find("{")
    while start != -1:
        try:
            value, end = decoder.raw_decode(printed, start)
        except ValueError:
            start = printed.find("{", start + 1)
            continue
        if isinstance(value, dict):
            found.append(value)
        start = printed.find("{", end)
    return found


def trusts_workflow(configs: list[dict], repo: str) -> bool:
    """Whether one of configs trusts the repo's publish workflow to publish."""
    return any(
        config.get("type") == "github"
        and config.get("file") == WORKFLOW
        and str(config.get("repository", "")).lower() == repo.lower()
        and "createPackage" in config.get("permissions", ["createPackage"])
        for config in configs
    )


def lacks(package: str, directory: Path) -> list[str] | None:
    """Each version tag on the directory's origin that npm doesn't have yet, oldest first, or
    None when npm doesn't have the package. Only what is on origin counts, so a tag not yet
    pushed is not expected."""
    published = versions(package)
    if published is None:
        return None
    git = ("git", "-C", str(directory), "ls-remote", "--tags", "--refs", "origin")
    listed = output(*git, env={"GIT_TERMINAL_PROMPT": "0"}).splitlines()
    return missing([line.partition("\trefs/tags/")[2] for line in listed], published)


def missing(tags: list[str], published: frozenset[str]) -> list[str]:
    """The version tags whose version isn't published, oldest first. Tags older than the oldest
    version published are left out: they were released before the package was on npm."""
    tagged = sorted((tag for tag in tags if version_tags.is_version(tag)), key=version_tags.key)
    oldest = min(
        (version_tags.key(v) for v in published if version_tags.is_version(v)), default=None
    )
    return [
        tag
        for tag in tagged
        if (oldest is None or version_tags.key(tag) >= oldest)
        and tag.removeprefix("v") not in published
    ]


def _npm(directory: Path) -> tuple[str, ...]:
    """npm from the directory's devbox, run in the directory."""
    return ("devbox", "run", "--quiet", "--config", str(directory), "--", "npm")


def _in_terminal(*args: str) -> tuple[int, str]:
    """Runs a command in a pseudo-terminal, so it can ask the user for a one-time password,
    showing everything it prints. Returns its exit status and what it printed."""
    chunks = []

    def read(fd: int) -> bytes:
        data = os.read(fd, 1024)
        chunks.append(data)
        return data

    status = pty.spawn(list(args), read)
    printed = b"".join(chunks).decode(errors="replace").replace("\r\n", "\n")
    return os.waitstatus_to_exitcode(status), printed
