"""Behaviour of the branch plugin's showing of where a repository's HEAD is."""

from repo_list.plugin import Note
from repo_list.plugins.branch import Head, assess


def test_the_default_branch_is_shown_dimmed():
    assert assess(Head("main", "3f2a1c9", default="main")) == [Note("main", quiet=True)]


def test_another_branch_is_shown_undimmed_so_it_stands_out():
    assert assess(Head("spike", "3f2a1c9", default="main")) == [Note("spike", quiet=False)]


def test_a_branch_is_shown_undimmed_when_the_default_branch_is_unknown():
    assert assess(Head("main", "3f2a1c9", default=None)) == [Note("main", quiet=False)]


def test_a_detached_head_is_shown_by_its_commit():
    assert assess(Head(None, "3f2a1c9", default="main")) == [Note("@3f2a1c9", quiet=False)]
