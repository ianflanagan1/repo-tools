"""Running git in a repository, as the scan and every plugin do."""

import os
import subprocess
from pathlib import Path


def git(repo: Path, *args: str, check: bool = True) -> str:
    """Runs git in repo and returns its output, stripped; with check=False, "" on failure.

    With check, a failure raises CalledProcessError, which the scan reports as git failing to read
    the repository.
    """
    result = run(repo, *args)
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, result.args, stderr=result.stderr)
    return result.stdout.strip() if result.returncode == 0 else ""


def run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Runs git in repo, never stopping to ask for a password."""
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, env=batch_env()
    )


def batch_env() -> dict[str, str]:
    """The environment for a git command that talks to a remote: it fails rather than stopping
    to ask for a password."""
    return os.environ | {
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_SSH_COMMAND": os.environ.get("GIT_SSH_COMMAND", "ssh") + " -o BatchMode=yes",
    }


# The marker git leaves in the git directory during each operation that a commit, rebase or merge
# must not interrupt.
IN_PROGRESS = {
    "MERGE_HEAD": "a merge",
    "rebase-merge": "a rebase",
    "rebase-apply": "a rebase",
    "CHERRY_PICK_HEAD": "a cherry-pick",
    "REVERT_HEAD": "a revert",
}


def in_progress(repo: Path) -> str | None:
    """The operation in progress in repo, such as "a merge", or None."""
    for marker, operation in IN_PROGRESS.items():
        if (repo / git(repo, "rev-parse", "--git-path", marker)).exists():
            return operation
    return None
