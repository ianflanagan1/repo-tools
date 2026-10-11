"""GitHub operations, through gh, for the github commands and other services' commands."""

import json
import re
from pathlib import Path

from cli_kit.errors import Failure, Precondition
from cli_kit.proc import output, run, succeeds


def current_user() -> str:
    """The login of the account gh is logged in as."""
    return output("gh", "api", "user", "--jq", ".login")


def full_name(name: str) -> str:
    """owner/name for a repo given as owner/name, or as a name owned by the current user."""
    return name if "/" in name else f"{current_user()}/{name}"


def exists(repo: str) -> bool:
    return succeeds("gh", "repo", "view", repo)


def visibility(repo: str) -> str:
    """public, private or internal."""
    jq = ".visibility | ascii_downcase"
    return output("gh", "repo", "view", repo, "--json", "visibility", "--jq", jq)


def create(repo: str, visibility: str, description: str) -> None:
    run("gh", "repo", "create", repo, f"--{visibility}", "--description", description)


def is_archived(repo: str) -> bool:
    return (
        output("gh", "repo", "view", repo, "--json", "isArchived", "--jq", ".isArchived") == "true"
    )


def archive(repo: str) -> None:
    output("gh", "repo", "archive", repo, "--yes")


def delete(repo: str, token: str) -> None:
    """Deletes the repo, using token, which needs the delete_repo scope, instead of gh's login.

    The token reaches gh through its environment, so it never appears on a command line.
    """
    output("gh", "repo", "delete", repo, "--yes", env={"GH_TOKEN": token})


def release_exists(repo: str, tag: str) -> bool:
    return succeeds("gh", "release", "view", tag, "--repo", repo)


def create_release(repo: str, tag: str) -> None:
    """Creates the GitHub release of an existing tag, with notes generated from its commits."""
    output("gh", "release", "create", tag, "--repo", repo, "--verify-tag", "--generate-notes")


def current_name(repo: str) -> str | None:
    """The owner/name the repo goes by now, following GitHub's redirect from a name it was
    renamed from; None when gh can't see it."""
    command = ("gh", "api", f"repos/{repo}", "--jq", ".full_name")
    return output(*command) if succeeds(*command) else None


def rename(repo: str, new_name: str) -> None:
    """Renames the repo, keeping its owner. GitHub redirects the old name until a repo takes it."""
    output("gh", "repo", "rename", new_name, "--repo", repo, "--yes")


def renamed_url(url: str, repo: str) -> str:
    """The GitHub remote URL url, in the same SSH or HTTPS form, naming repo instead."""
    return re.sub(r"(github\.com[:/]).+?((?:\.git)?)$", rf"\g<1>{repo}\g<2>", url)


def repo_from_url(url: str) -> str:
    """The owner/name of a GitHub remote URL, in SSH or HTTPS form."""
    match = re.search(r"github\.com[:/](.+?)(?:\.git)?$", url)
    if not match:
        raise Precondition(f"{url} is not a GitHub repo.")
    return match.group(1)


def origin_url(directory: Path) -> str | None:
    """The URL of the directory's origin remote as configured, or None when it has none.

    Read from the config rather than `git remote get-url`, which applies url.*.insteadOf
    rewrites and so can hide which GitHub repo the remote names.
    """
    git = ("git", "-C", str(directory), "config", "--get", "remote.origin.url")
    return output(*git) if succeeds(*git) else None


def hook_urls(repo: str) -> list[str]:
    """The URLs the repo's webhooks call."""
    return output("gh", "api", f"repos/{repo}/hooks", "--jq", ".[].config.url").splitlines()


def add_hook(repo: str, url: str, secret: str) -> None:
    """Adds a webhook calling url with JSON on each push. The secret is sent on stdin."""
    hook = {
        "name": "web",
        "active": True,
        "events": ["push"],
        "config": {"url": url, "content_type": "json", "secret": secret},
    }
    try:
        output(
            "gh",
            "api",
            f"repos/{repo}/hooks",
            "--method",
            "POST",
            "--input",
            "-",
            input=json.dumps(hook),
        )
    except Failure:
        raise Failure(
            "Couldn't add the webhook.", "The gh token needs the admin:repo_hook scope."
        ) from None


def push(*command: str) -> bool:
    """Runs a `git push --porcelain` and says whether it updated anything on the remote.

    Each ref line starts with a flag: "=" up to date, " " fast-forward, "*" new, "+" forced.
    """
    lines = output(*command).splitlines()
    return any(line[:1] in (" ", "*", "+") and "\t" in line for line in lines)
