"""Behaviour of the branch plugin's showing of where a repository's HEAD is."""

from repo_list.plugin import Note
from repo_list.plugins.branch import Head, assess


def test_the_trunk_is_shown_dimmed():
    assert assess(Head("main", "3f2a1c9", trunk="main")) == [Note("main", quiet=True)]


def test_another_branch_is_shown_undimmed_so_it_stands_out():
    assert assess(Head("spike", "3f2a1c9", trunk="main")) == [Note("spike", quiet=False)]


def test_a_branch_is_shown_undimmed_when_the_trunk_is_unknown():
    assert assess(Head("main", "3f2a1c9", trunk=None)) == [Note("main", quiet=False)]


def test_a_detached_head_is_shown_by_its_commit():
    assert assess(Head(None, "3f2a1c9", trunk="main")) == [Note("@3f2a1c9", quiet=False)]
