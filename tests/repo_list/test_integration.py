"""Behaviour of the integration policy: which branches each directory reports on, what it reports
about them, and what repo-fix does about it, in each integration."""

from pathlib import Path

import pytest

from repo_list.integration import (
    BehindBase,
    BehindUpstream,
    Branch,
    CatchUp,
    Conflicts,
    Diverged,
    FastForward,
    Head,
    Integration,
    OnTrunk,
    Push,
    RebaseOnUpstream,
    Unmerged,
    Unpushed,
    Worktree,
    assess_branch,
    assess_head,
    branches_to_check,
    fix_order,
    integration_icon,
    plan_catch_up,
    plan_pulls,
    plan_pushes,
)

DIRECT = Integration.DIRECT
PR_INTEGRATIONS = [Integration.PR_REBASE, Integration.PR_MERGE]


def branch(name: str = "main", **facts) -> Branch:
    """A branch level with its upstream and trunk, checked out in this directory; main is the
    trunk."""
    defaults = dict(
        here=True,
        trunk=name == "main",
        has_upstream=True,
        unpushed=0,
        behind=0,
        unmerged=0,
    )
    return Branch(name, **{**defaults, **facts})


def head(name: str | None = "feature", **facts) -> Head:
    defaults = dict(base="main", behind_base=0, conflicts=False)
    return Head(name, **{**defaults, **facts})


# --- Which branches a directory reports on


def worktree(path: str, branch: str | None) -> Worktree:
    return Worktree(Path(path), branch, prunable=False)


WORKTREES = [worktree("/a", "main"), worktree("/a-wt1", "feature"), worktree("/a-wt2", None)]
BRANCHES = ["feature", "main", "parked", "spike"]


def test_the_main_worktree_reports_its_own_branch_and_every_one_no_worktree_has():
    found = branches_to_check("main", True, BRANCHES, WORKTREES, "main")
    assert found == ["main", "parked", "spike"]


def test_a_linked_worktree_reports_only_its_own_branch():
    assert branches_to_check("feature", False, BRANCHES, WORKTREES, "main") == ["feature"]


def test_a_detached_linked_worktree_reports_no_branch():
    assert branches_to_check(None, False, BRANCHES, WORKTREES, "main") == []


def test_a_branch_with_no_commits_yet_is_not_reported_as_there_is_nothing_on_it():
    assert branches_to_check("main", True, [], [worktree("/a", "main")], "main") == []


def test_the_trunk_comes_first_so_it_is_brought_level_before_the_branches_on_it():
    worktrees = [worktree("/a", "spike"), worktree("/a-wt1", "feature")]
    found = branches_to_check("spike", True, BRANCHES, worktrees, "main")
    assert found == ["main", "parked", "spike"]


def test_the_branch_of_a_worktree_that_no_longer_exists_counts_as_checked_out_by_none():
    worktrees = [worktree("/a", "main"), Worktree(Path("/gone"), "feature", prunable=True)]
    found = branches_to_check("main", True, BRANCHES, worktrees, "main")
    assert found == ["main", "feature", "parked", "spike"]


# --- What a branch's state amounts to, with each integration


def test_with_direct_integration_the_trunk_reports_commits_to_push_and_to_pull():
    assert assess_branch(branch(unpushed=2, behind=1), DIRECT, has_remote=True) == [
        Unpushed("main", 2),
        BehindUpstream("main", 1),
    ]


def test_with_direct_integration_another_branch_reports_the_work_not_yet_landed_on_the_trunk():
    found = assess_branch(branch("feature", unpushed=2, unmerged=2), DIRECT, has_remote=True)
    assert found == [Unmerged("feature", 2)]


def test_with_direct_integration_a_branch_fully_landed_on_the_trunk_needs_nothing():
    assert assess_branch(branch("feature", unpushed=0, unmerged=0), DIRECT, True) == []


@pytest.mark.parametrize("integration", PR_INTEGRATIONS)
def test_with_pr_integration_commits_on_the_trunk_belong_on_a_branch(integration):
    assert assess_branch(branch(unpushed=1), integration, has_remote=True) == [OnTrunk("main", 1)]


@pytest.mark.parametrize("integration", PR_INTEGRATIONS)
def test_with_pr_integration_another_branch_reports_commits_to_push_and_to_pull(integration):
    found = assess_branch(branch("feature", unpushed=2, behind=1, unmerged=3), integration, True)
    assert found == [Unpushed("feature", 2), BehindUpstream("feature", 1)]


@pytest.mark.parametrize("integration", [DIRECT, *PR_INTEGRATIONS])
def test_without_a_remote_nothing_is_unpushed_as_the_missing_remote_is_reported_instead(
    integration,
):
    assert (
        assess_branch(branch(unpushed=2, has_upstream=False), integration, has_remote=False) == []
    )


@pytest.mark.parametrize("integration", [DIRECT, *PR_INTEGRATIONS])
def test_with_the_trunk_unknown_every_branch_reports_commits_to_push_and_to_pull(integration):
    found = assess_branch(branch("feature", trunk=None, unpushed=1, behind=2), integration, True)
    assert found == [Unpushed("feature", 1), BehindUpstream("feature", 2)]


# --- How far HEAD is behind the branch it lands on


@pytest.mark.parametrize("name", ["feature", None])
def test_a_head_behind_its_base_is_reported_with_how_far(name):
    assert assess_head(head(name, behind_base=3), DIRECT) == [BehindBase("main", 3)]


def test_a_head_whose_catching_up_would_conflict_is_reported_as_conflicting():
    found = assess_head(head(behind_base=3, conflicts=True), DIRECT)
    assert found == [Conflicts("main")]


def test_a_head_level_with_its_base_needs_nothing():
    assert assess_head(head(behind_base=0), DIRECT) == []


@pytest.mark.parametrize("integration", PR_INTEGRATIONS)
def test_with_pr_integration_a_detached_head_is_not_caught_up_as_it_cannot_be_pushed(integration):
    assert assess_head(head(None, base="origin/main", behind_base=3), integration) == []


@pytest.mark.parametrize("integration", PR_INTEGRATIONS)
def test_with_pr_integration_a_branch_is_caught_up_with_the_trunk_on_the_remote(integration):
    found = assess_head(head(base="origin/main", behind_base=1), integration)
    assert found == [BehindBase("origin/main", 1)]


# --- What repo-fix pulls


def test_a_branch_only_behind_its_upstream_is_fast_forwarded():
    assert plan_pulls([branch(behind=2)], DIRECT) == [FastForward("main", here=True)]


def test_with_direct_integration_a_diverged_trunk_checked_out_here_is_rebased_on_its_upstream():
    assert plan_pulls([branch(unpushed=1, behind=2)], DIRECT) == [RebaseOnUpstream("main")]


def test_with_direct_integration_a_diverged_trunk_checked_out_nowhere_is_left_alone():
    found = plan_pulls([branch(here=False, unpushed=1, behind=2)], DIRECT)
    assert found == [Diverged("main")]


@pytest.mark.parametrize("integration", PR_INTEGRATIONS)
def test_with_pr_integration_a_diverged_branch_is_left_alone(integration):
    found = plan_pulls(
        [branch(unpushed=1, behind=2), branch("feature", unpushed=1, behind=1)], integration
    )
    assert found == [Diverged("main"), Diverged("feature")]


def test_a_branch_level_with_its_upstream_is_not_pulled():
    assert plan_pulls([branch(unpushed=3)], DIRECT) == []


# --- What repo-fix catches up


def test_with_local_and_pr_rebase_integration_head_is_rebased_onto_its_base():
    assert plan_catch_up(head(behind_base=2), DIRECT) == CatchUp("main", rebase=True)
    assert plan_catch_up(head(behind_base=2), Integration.PR_REBASE) == CatchUp("main", True)


def test_with_pr_merge_integration_the_base_is_merged_into_head():
    assert plan_catch_up(head(behind_base=2), Integration.PR_MERGE) == CatchUp("main", False)


def test_a_head_expected_to_conflict_is_still_caught_up():
    found = plan_catch_up(head(behind_base=2, conflicts=True), DIRECT)
    assert found == CatchUp("main", rebase=True)


def test_a_head_level_with_its_base_is_not_caught_up():
    assert plan_catch_up(head(behind_base=0), DIRECT) is None


# --- What repo-fix pushes


def test_with_direct_integration_only_the_trunk_is_pushed():
    found = plan_pushes([branch(unpushed=1), branch("feature", unpushed=2, unmerged=2)], DIRECT)
    assert found == [Push("main", force=False)]


@pytest.mark.parametrize("integration", PR_INTEGRATIONS)
def test_with_pr_integration_the_trunk_is_never_pushed(integration):
    assert plan_pushes([branch(unpushed=1)], integration) == []


def test_with_pr_merge_integration_a_branch_is_pushed_without_force():
    found = plan_pushes([branch("feature", unpushed=1)], Integration.PR_MERGE)
    assert found == [Push("feature", force=False)]


def test_with_pr_rebase_integration_a_branch_is_pushed_with_a_lease_even_after_its_rebase():
    found = plan_pushes([branch("feature", unpushed=1, behind=2)], Integration.PR_REBASE)
    assert found == [Push("feature", force=True)]


def test_a_diverged_branch_is_not_pushed_outside_pr_rebase_integration():
    assert plan_pushes([branch(unpushed=1, behind=1)], DIRECT) == []
    assert plan_pushes([branch("feature", unpushed=1, behind=1)], Integration.PR_MERGE) == []


def test_with_the_trunk_unknown_any_branch_with_commits_to_push_is_pushed():
    assert plan_pushes([branch("feature", trunk=None, unpushed=1)], DIRECT) == [
        Push("feature", force=False)
    ]


# --- The order repo-fix takes a repository's directories in


def test_the_directory_with_the_trunk_checked_out_goes_first_and_the_rest_in_their_order():
    directories = [
        ("a", "repo", "spike", True),
        ("a-wt1", "repo", None, False),
        ("a-wt2", "repo", "main", False),
    ]
    assert fix_order(directories, {"repo": "main"}) == ["a-wt2", "a", "a-wt1"]


def test_with_the_trunk_checked_out_nowhere_the_main_worktree_goes_first_as_it_updates_it():
    directories = [("a-wt1", "repo", "feature", False), ("a", "repo", "spike", True)]
    assert fix_order(directories, {"repo": "main"}) == ["a", "a-wt1"]


def test_each_repository_keeps_its_place_among_the_others():
    directories = [
        ("a", "one", "feature", True),
        ("a-wt1", "one", "main", False),
        ("b", "two", "main", True),
        ("notes", None, None, False),
    ]
    order = fix_order(directories, {"one": "main", "two": "main"})
    assert order == ["a-wt1", "a", "b", "notes"]


# --- The integration's icon


def test_each_integration_has_its_own_icon_and_an_unset_integration_the_spanner():
    assert [integration_icon(m) for m in Integration] == ["🏠", "📏", "🔀"]
    assert integration_icon(None) == "🔧"
