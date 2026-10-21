"""Version tags, [v]MAJOR.MINOR.PATCH, as every host's release command makes them.

Pre-releases such as v2.0.0-beta1 aren't versions here.
"""

import re

LEVELS = ["patch", "minor", "major"]
VERSION = re.compile(r"^(v?)(\d+)\.(\d+)\.(\d+)$")


def is_version(tag: str) -> bool:
    return VERSION.match(tag) is not None


def key(tag: str) -> tuple[int, int, int]:
    """The version tag's numbers, for ordering versions."""
    _, major, minor, patch = VERSION.match(tag).groups()
    return int(major), int(minor), int(patch)


def next_version(tags: list[str], level: str) -> str:
    """The highest version among tags, bumped at level: patch, minor or major. With none, it's
    0.0.0 bumped, v-style."""
    versions = [t for t in tags if is_version(t)]
    highest = max(versions, key=key, default="v0.0.0")
    prefix = VERSION.match(highest)[1]
    major, minor, patch = key(highest)
    match level:
        case "major":
            major, minor, patch = major + 1, 0, 0
        case "minor":
            minor, patch = minor + 1, 0
        case _:
            patch += 1
    return f"{prefix}{major}.{minor}.{patch}"
