"""Showing folders and their problems as repo-list lists them."""

from pathlib import Path

from cli_kit.colour import BOLD, GREEN, GREY, RED, YELLOW, Style, wants_colour

from repo_list.scan import (
    Behind,
    Detached,
    FetchFailed,
    Folder,
    GitFailed,
    NoRemote,
    NotARepo,
    NotOnPackagist,
    PackagistBehind,
    PackagistFailed,
    Problem,
    Stashed,
    Uncommitted,
    Unpushed,
)


def describe(problem: Problem) -> str:
    """The problem as repo-list shows it, marked by its emoji."""
    match problem:
        case Uncommitted(files):
            return f"📝 {count(files, 'uncommitted file')}"
        case Unpushed(branch, commits):
            return f"📤 {commits} unpushed on {branch}"
        case Behind(branch, commits):
            return f"📥 {commits} behind on {branch}"
        case Detached(commits):
            return f"👻 {count(commits, 'commit')} on detached HEAD"
        case Stashed(stashes):
            return f"📦 {count(stashes, 'stash')}"
        case NoRemote():
            return "🔌 no remote"
        case NotARepo():
            return "📁 not a git repository"
        case FetchFailed():
            return "📡 fetch failed"
        case GitFailed():
            return "💥 git failed"
        case NotOnPackagist():
            return "🐘 not on Packagist"
        case PackagistBehind(lacking):
            return f"🐘 Packagist lacks {', '.join(lacking)}"
        case PackagistFailed():
            return "🐘 Packagist check failed"


def count(n: int, noun: str) -> str:
    """'1 file', '2 files'."""
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def show(root: Path, folders: list[Folder]) -> int:
    """Prints each folder by its path from root, then the total needing attention.

    Returns the exit status: 0 all clean, 1 something needs attention.
    """
    colour = Style(enabled=wants_colour())
    width = max(len(str(f.path.relative_to(root))) for f in folders)
    for folder in folders:
        path = folder.path.relative_to(root)
        parent = "" if path.parent == Path(".") else f"{path.parent}/"
        name = colour(GREY, parent) + colour(BOLD, path.name)
        if folder.problems:
            padding = " " * (width - len(str(path)))
            problems = "  ".join(describe(p) for p in folder.problems)
            print(f"{colour(RED, '✘')} {name}{padding}  {colour(YELLOW, problems)}")
        else:
            print(f"{colour(GREEN, '✔')} {name}")

    attention = sum(1 for f in folders if f.problems)
    print()
    if not attention:
        print(colour(GREEN, f"✔ All {len(folders)} clean"))
        return 0
    print(colour(RED, f"✘ {attention} of {len(folders)} need attention"))
    return 1
