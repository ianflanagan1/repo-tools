"""A local clone's origin and pushes, against real git repositories."""

import subprocess

from repo_tools import clone


def test_reads_origin_as_configured_ignoring_url_rewrites(tmp_path):
    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)

    git("init", "--quiet")
    git("remote", "add", "origin", "git@github.com:me/thing.git")
    git("config", "url./somewhere/else.git.insteadOf", "git@github.com:me/thing.git")
    assert clone.origin_url(tmp_path) == "git@github.com:me/thing.git"


def test_has_no_origin_for_a_repo_without_one(tmp_path):
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    assert clone.origin_url(tmp_path) is None


def test_a_push_that_updated_nothing_says_so(tmp_path):
    def git(*args: str) -> None:
        subprocess.run(
            ["git", "-C", str(tmp_path / "work"), *args], check=True, capture_output=True
        )

    subprocess.run(["git", "init", "--quiet", "--bare", str(tmp_path / "remote.git")], check=True)
    subprocess.run(
        ["git", "init", "--quiet", "--initial-branch", "main", str(tmp_path / "work")], check=True
    )
    git(
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t",
        "commit",
        "--quiet",
        "--allow-empty",
        "--message",
        "one",
    )
    git("remote", "add", "origin", str(tmp_path / "remote.git"))
    push = ("git", "-C", str(tmp_path / "work"), "push", "--porcelain", "origin", "main")
    assert clone.push(*push)
    assert not clone.push(*push)
