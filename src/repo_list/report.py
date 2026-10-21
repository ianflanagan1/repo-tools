"""Showing folders and their problems as repo-list lists them."""

from pathlib import Path

from cli_kit.colour import BOLD, GREEN, GREY, RED, YELLOW, Style

from repo_list.scan import Folder


def name(path: Path, colour: Style) -> str:
    """A path from the root, its parent grey and its last part bold."""
    parent = "" if path.parent == Path(".") else f"{path.parent}/"
    return colour(GREY, parent) + colour(BOLD, path.name)


def show(root: Path, folders: list[Folder]) -> int:
    """Prints each folder by its path from root, then the total needing attention.

    Returns the exit status: 0 all clean, 1 something needs attention.
    """
    colour = Style.for_stream()
    width = max(len(str(f.path.relative_to(root))) for f in folders)
    for folder in folders:
        path = folder.path.relative_to(root)
        if folder.problems:
            padding = " " * (width - len(str(path)))
            problems = "  ".join(p.describe() for p in folder.problems)
            print(f"{colour(RED, '✘')} {name(path, colour)}{padding}  {colour(YELLOW, problems)}")
        else:
            print(f"{colour(GREEN, '✔')} {name(path, colour)}")

    attention = sum(1 for f in folders if f.problems)
    print()
    if not attention:
        print(colour(GREEN, f"✔ All {len(folders)} clean"))
        return 0
    print(colour(RED, f"✘ {attention} of {len(folders)} need attention"))
    return 1
