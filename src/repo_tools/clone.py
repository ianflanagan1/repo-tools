"""A local clone of a repo on any host: the remote it names, and pushing from it."""

from pathlib import Path

from cli_kit.proc import output, succeeds


def origin_url(directory: Path) -> str | None:
    """The URL of the directory's origin remote as configured, or None when it has none.

    Read from the config rather than `git remote get-url`, which applies url.*.insteadOf
    rewrites and so can hide which repo the remote names.
    """
    git = ("git", "-C", str(directory), "config", "--get", "remote.origin.url")
    return output(*git) if succeeds(*git) else None


def push(*command: str) -> bool:
    """Runs a `git push --porcelain` and says whether it updated anything on the remote.

    Each ref line starts with a flag: "=" up to date, " " fast-forward, "*" new, "+" forced.
    """
    lines = output(*command).splitlines()
    return any(line[:1] in (" ", "*", "+") and "\t" in line for line in lines)
