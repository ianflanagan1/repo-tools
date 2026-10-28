from repo_list.plugins.lock import upgrades

DRY_RUN = """Resolved 17 packages in 667ms
Update pluggy v1.6.0 -> v1.7.0
Add tomli v2.2.1
Remove colorama v0.4.6
"""


def test_the_upgrades_are_the_packages_uv_says_it_updates_adds_and_removes():
    assert upgrades(DRY_RUN) == [
        "Update pluggy v1.6.0 -> v1.7.0",
        "Add tomli v2.2.1",
        "Remove colorama v0.4.6",
    ]


def test_a_lock_that_is_already_up_to_date_has_no_upgrades():
    assert upgrades("Resolved 17 packages in 2ms\n") == []
