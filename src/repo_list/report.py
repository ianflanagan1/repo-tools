"""Showing folders and their problems as repo-list lists them."""

from pathlib import Path

from cli_kit.colour import BOLD, GREEN, GREY, RED, YELLOW, Style

from repo_list.scan import Folder


def name(path: Path, colour: Style) -> str:
    """A path from the root, its parent grey and its last part bold."""
    parent = "" if path.parent == Path(".") else f"{path.parent}/"
    return colour(GREY, parent) + colour(BOLD, path.name)


def notes(folder: Folder, colour: Style) -> str:
    """The folder's notes, each dimmed if quiet."""
    return "  ".join(colour(GREY, n.describe()) if n.quiet else n.describe() for n in folder.notes)


def show(root: Path, folders: list[Folder]) -> int:
    """Prints each folder by its path from root, then the total needing attention.

    Returns the exit status: 0 all clean, 1 something needs attention.
    """
    colour = Style.for_stream()
    width = max(len(str(f.path.relative_to(root))) for f in folders)
    notes_width = max(len(notes(f, Style(False))) for f in folders)
    for folder in folders:
        path = folder.path.relative_to(root)
        mark = colour(RED, "✘") if folder.problems else colour(GREEN, "✔")
        columns = [name(path, colour) + " " * (width - len(str(path)))]
        if notes_width:
            plain = notes(folder, Style(False))
            columns.append(notes(folder, colour) + " " * (notes_width - len(plain)))
        columns.append(colour(YELLOW, "  ".join(p.describe() for p in folder.problems)))
        print(f"{mark} {'  '.join(columns)}".rstrip())

    attention = sum(1 for f in folders if f.problems)
    print()
    if not attention:
        print(colour(GREEN, f"✔ All {len(folders)} clean"))
        return 0
    print(colour(RED, f"✘ {attention} of {len(folders)} need attention"))
    return 1
