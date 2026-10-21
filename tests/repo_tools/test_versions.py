"""Version tags and the next one at each level."""

import pytest

from repo_tools import versions


@pytest.mark.parametrize(
    ("level", "expected"), [("patch", "v1.2.4"), ("minor", "v1.3.0"), ("major", "v2.0.0")]
)
def test_bumps_the_highest_version_at_the_level(level, expected):
    assert versions.next_version(["v1.2.3", "v1.10.0-beta1", "v0.9.9", "latest"], level) == expected


def test_orders_versions_by_number_not_text():
    assert versions.next_version(["1.9.0", "1.10.0"], "patch") == "1.10.1"


def test_keeps_the_highest_tags_style_without_a_v():
    assert versions.next_version(["2.0.0"], "minor") == "2.1.0"


def test_without_versions_starts_from_zero_v_style():
    assert versions.next_version([], "minor") == "v0.1.0"


def test_a_pre_release_is_not_a_version():
    assert not versions.is_version("v2.0.0-beta1")
