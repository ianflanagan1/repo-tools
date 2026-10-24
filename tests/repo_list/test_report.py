"""Behaviour of measuring what repo-list prints, so its columns line up in a terminal."""

from repo_list.hosts import Visibility
from repo_list.integration import Integration
from repo_list.plugins.remote import NO_REMOTE, icon
from repo_list.report import width


def test_plain_text_takes_a_column_for_each_character():
    assert width("main  @3f2a1c9") == 14


def test_a_wide_emoji_takes_two_columns():
    assert width("🤖 Claude working") == 17


def test_an_emoji_selector_takes_no_column_of_its_own():
    assert width("⚡️") == 2


def test_every_badge_is_two_columns_wide_so_badges_line_up():
    icons = [m.icon for m in Integration] + ["🔧", NO_REMOTE] + [icon(v) for v in Visibility]
    assert [width(i) for i in icons] == [2] * len(icons)
