from repo_list.plugins.lock import task_names


def test_the_tasks_are_those_task_lists_by_name():
    listing = '{"tasks": [{"name": "check", "desc": "All"}, {"name": "lint-file"}]}'
    assert task_names(listing) == {"check", "lint-file"}


def test_a_listing_that_cannot_be_parsed_has_no_tasks():
    assert task_names("task: No Taskfile found") == set()
    assert task_names('["check"]') == set()
