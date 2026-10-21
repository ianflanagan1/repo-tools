"""Packagist operations, for the packagist commands and other services' commands.

The main API token submits packages. The safe token, which can only trigger updates, is the
GitHub webhook secret, because GitHub stores it.
"""

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from cli_kit.credentials import Token
from cli_kit.outcome import Failure
from cli_kit.proc import output

PACKAGIST = "https://packagist.org"
# Composer's metadata, which is what installs see. The packages/<name>.json API is cached for
# up to twelve hours, too long to tell whether an update has landed.
REPO = "https://repo.packagist.org"
MAIN_TOKEN = Token(
    service="packagist-api-token",
    name="Packagist main API token",
    username="packagist-username",
    create="Copy the main API token from your profile at https://packagist.org/profile/.",
)
SAFE_TOKEN = Token(
    service="packagist-safe-api-token",
    name="Packagist safe API token",
    username="packagist-username",
    create="Copy the safe API token from your profile at https://packagist.org/profile/.",
)


def package_url(package: str) -> str:
    return f"{PACKAGIST}/packages/{package}"


def package_exists(package: str) -> bool:
    try:
        with urllib.request.urlopen(f"{package_url(package)}.json"):
            return True
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return False
        raise Failure(f"Packagist answered {error.code} when looking up {package}.") from None


def submit(repository_url: str) -> None:
    """Submits the package in the repository at repository_url, using the main token."""
    main = MAIN_TOKEN.read()
    request = urllib.request.Request(
        f"{PACKAGIST}/api/create-package",
        data=json.dumps({"repository": {"url": repository_url}}).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {main.username}:{main.token}",
        },
        method="POST",
    )
    try:
        urllib.request.urlopen(request).close()
    except urllib.error.HTTPError as error:
        body = error.read().decode(errors="replace").strip()
        raise Failure("Packagist refused the submission.", body) from None


def github_hook() -> tuple[str, str]:
    """The URL and secret of the GitHub webhook that tells Packagist about pushes."""
    safe = SAFE_TOKEN.read()
    return f"{PACKAGIST}/api/github?username={safe.username}", safe.token


def repository(package: str) -> str | None:
    """The repository URL Packagist updates the package from, or None when it doesn't have it.
    Packagist's list is cached for up to five minutes."""
    vendor = package.split("/")[0]
    url = f"{PACKAGIST}/packages/list.json?vendor={vendor}&fields[]=repository"
    try:
        with urllib.request.urlopen(url) as response:
            packages = json.load(response)["packages"]
    except urllib.error.HTTPError as error:
        raise Failure(
            f"Packagist answered {error.code} when listing {vendor}'s packages."
        ) from None
    return packages.get(package, {}).get("repository") if isinstance(packages, dict) else None


def edit_repository(package: str, repository_url: str) -> None:
    """Points the package at the repository at repository_url, using the main token."""
    main = MAIN_TOKEN.read()
    request = urllib.request.Request(
        f"{PACKAGIST}/api/packages/{package}",
        data=json.dumps({"repository": repository_url}).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {main.username}:{main.token}",
        },
        method="PUT",
    )
    try:
        urllib.request.urlopen(request).close()
    except urllib.error.HTTPError as error:
        body = error.read().decode(errors="replace").strip()
        raise Failure("Packagist refused the new repository URL.", body) from None


def update(package: str) -> None:
    """Asks Packagist to update the package from its repository, using the safe token. The
    update runs later, on Packagist's queue."""
    safe = SAFE_TOKEN.read()
    request = urllib.request.Request(
        f"{PACKAGIST}/api/update-package",
        data=json.dumps({"repository": package_url(package)}).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {safe.username}:{safe.token}",
        },
        method="POST",
    )
    try:
        urllib.request.urlopen(request).close()
    except urllib.error.HTTPError as error:
        body = error.read().decode(errors="replace").strip()
        raise Failure("Packagist refused the update.", body) from None


@dataclass(frozen=True)
class Offered:
    """What Packagist offers of a package for Composer to install."""

    versions: frozenset[str]
    """Each tagged version, named as tagged, such as v1.2.0."""
    commits: frozenset[str]
    """The commit each dev branch is at."""


def offered(package: str) -> Offered | None:
    """What Packagist offers of the package, or None when it doesn't have the package."""
    tagged = _p2(f"{REPO}/p2/{package}.json")
    dev = _p2(f"{REPO}/p2/{package}~dev.json")
    if tagged is None and dev is None:
        return None
    return Offered(
        frozenset(v["version"] for v in _expand(tagged or [])),
        frozenset(v["source"]["reference"] for v in _expand(dev or []) if "source" in v),
    )


def lacks(package: str, directory: Path) -> list[str] | None:
    """What on the directory's origin Packagist doesn't offer yet, in name order: each version
    tag it lacks, and each branch whose commit it lacks. None when it doesn't have the package.

    Only what is on origin counts, so work not yet pushed is not expected.
    """
    offer = offered(package)
    if offer is None:
        return None
    lacking = []
    for line in output(*_git(directory), "ls-remote", "--heads", "--tags", "origin").splitlines():
        commit, _, ref = line.partition("\t")
        if branch := _strip(ref, "refs/heads/"):
            if commit not in offer.commits:
                lacking.append(branch)
        elif (tag := _strip(ref, "refs/tags/")) and VERSION_TAG.match(tag):
            if tag not in offer.versions:
                lacking.append(tag)
    return sorted(lacking)


# The tags Composer reads as versions, such as v1.2.0, 1.2 or 2.0.0-beta1.
VERSION_TAG = re.compile(r"^v?\d+(\.\d+){0,3}([-.]?[a-zA-Z]+\.?\d*)?$")


def _strip(ref: str, prefix: str) -> str:
    """ref without prefix, or "" when it doesn't start with it. A peeled tag, ending ^{}, is
    the same tag again, so it is "" too."""
    return ref.removeprefix(prefix) if ref.startswith(prefix) and "^" not in ref else ""


def _git(directory: Path) -> tuple[str, ...]:
    """git in directory, failing rather than stopping to ask for a password."""
    ssh = os.environ.get("GIT_SSH_COMMAND", "ssh") + " -o BatchMode=yes"
    return ("env", "GIT_TERMINAL_PROMPT=0", f"GIT_SSH_COMMAND={ssh}", "git", "-C", str(directory))


def _p2(url: str) -> list[dict] | None:
    """The versions in a Composer metadata file, still minified, or None on a 404."""
    request = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
    try:
        with urllib.request.urlopen(request) as response:
            files = json.load(response)["packages"]
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise Failure(f"Packagist answered {error.code} for {url}.") from None
    except urllib.error.URLError as error:
        raise Failure("Couldn't reach Packagist.", str(error.reason)) from None
    return next(iter(files.values()), [])


def _expand(minified: list[dict]) -> list[dict]:
    """Composer's minified versions in full: each lists only the fields that differ from the
    version before it, with "__unset" for one it doesn't have."""
    expanded, current = [], {}
    for version in minified:
        current = {k: v for k, v in (current | version).items() if v != "__unset"}
        expanded.append(current)
    return expanded
