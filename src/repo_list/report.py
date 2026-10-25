"""Showing directories and their problems as repo-list lists them."""

import unicodedata
from pathlib import Path

from cli_kit.colour import BOLD, GREEN, GREY, RED, YELLOW, Style

from repo_list.plugin import Slot
from repo_list.scan import Directory

BLANK = "  "
"""An empty badge slot, as wide as a badge."""


def name(path: Path, colour: Style) -> str:
    """A path from the root, its parent grey and its last part bold."""
    parent = "" if path.parent == Path(".") else f"{path.parent}/"
    return colour(GREY, parent) + colour(BOLD, path.name)


def width(text: str) -> int:
    """How many columns text takes in a terminal: two for a wide character, such as most
    emoji, none for one that only modifies the character before it."""
    columns = 0
    for character in text:
        if unicodedata.combining(character) or character in "\ufe0f\u200d":
            continue
        columns += 2 if unicodedata.east_asian_width(character) in "WF" else 1
    return columns


def slot_widths(directories: list[Directory]) -> dict[Slot, int]:
    """How wide each slot's column is: its widest badges among directories, and at least a
    badge's width but for the package slot, which is left out when no directory has one."""
    widths = {slot: 0 if slot is Slot.PACKAGE else width(BLANK) for slot in Slot}
    for directory in directories:
        for slot, icons in directory.badges.items():
            widths[slot] = max(widths[slot], width(icons))
    return widths


def badges(directory: Directory, widths: dict[Slot, int]) -> str:
    """The directory's badges, each slot padded to its width, a blank where it has none."""
    found = directory.badges
    return " ".join(
        found.get(slot, "") + " " * (columns - width(found.get(slot, "")))
        for slot, columns in widths.items()
        if columns
    )


def notes(directory: Directory, colour: Style) -> str:
    """The directory's notes, each dimmed if quiet."""
    return "  ".join(
        colour(GREY, n.describe()) if n.quiet else n.describe() for n in directory.notes
    )


def show(root: Path, directories: list[Directory], clean_too: bool = False) -> int:
    """Prints each directory needing attention by its path from root, then the total needing it.

    Clean directories are listed too if clean_too is set, and counted in the total either way.
    Returns the exit status: 0 all clean, 1 something needs attention.
    """
    colour = Style.for_stream()
    listed = [f for f in directories if clean_too or f.problems]
    path_width = max((width(str(f.path.relative_to(root))) for f in listed), default=0)
    any_badges = any(f.badges for f in listed)
    widths = slot_widths(listed)
    notes_width = max((width(notes(f, Style(False))) for f in listed), default=0)
    for directory in listed:
        path = directory.path.relative_to(root)
        mark = colour(RED, "✘") if directory.problems else colour(GREEN, "✔")
        columns = [name(path, colour) + " " * (path_width - width(str(path)))]
        if notes_width:
            plain = notes(directory, Style(False))
            columns.append(notes(directory, colour) + " " * (notes_width - width(plain)))
        problems = colour(YELLOW, "  ".join(p.describe() for p in directory.problems))
        columns.append(f"{mark} {problems}")
        lead = badges(directory, widths) + " " if any_badges else ""
        print(f"{lead}{'  '.join(columns)}".rstrip())

    attention = sum(1 for f in directories if f.problems)
    if listed:
        print()
    if not attention:
        print(colour(GREEN, f"✔ All {len(directories)} clean"))
        return 0
    print(colour(RED, f"✘ {attention} of {len(directories)} need attention"))
    return 1
