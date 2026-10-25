from repo_list.dependencies import Order, edges, fix_first
from repo_tools.packages import Ecosystem, Name


def python(name: str) -> Name:
    return Name(Ecosystem.PYTHON, name)


# --- Which repositories depend on which


def test_a_repository_depends_on_another_whose_name_it_pins():
    called = {"kit": {python("cli-kit")}, "tools": {python("tools")}}
    pins = {"kit": set(), "tools": {python("cli-kit")}}
    assert edges(called, pins) == {"kit": set(), "tools": {"kit"}}


def test_a_name_pinned_in_another_ecosystem_is_not_a_dependency():
    called = {"kit": {python("kit")}, "app": set()}
    pins = {"kit": set(), "app": {Name(Ecosystem.NPM, "kit")}}
    assert edges(called, pins) == {"kit": set(), "app": set()}


def test_a_repository_never_depends_on_itself():
    called = {"kit": {python("kit")}}
    assert edges(called, {"kit": {python("kit")}}) == {"kit": set()}


def test_a_name_no_repository_is_called_is_no_dependency():
    assert edges({"app": set()}, {"app": {python("requests")}}) == {"app": set()}


# --- The order to fix them in


def test_repositories_with_no_dependencies_keep_their_order():
    assert fix_first(["b", "a", "c"], {}) == Order(["b", "a", "c"], [])


def test_a_dependency_is_fixed_before_its_dependant_however_they_are_named():
    assert fix_first(["a", "b", "c"], {"a": {"c"}}) == Order(["c", "a", "b"], [])


def test_a_dependency_of_a_dependency_is_fixed_first_of_all():
    assert fix_first(["a", "b", "c"], {"a": {"b"}, "b": {"c"}}) == Order(["c", "b", "a"], [])


def test_a_dependency_shared_by_several_is_fixed_once_before_the_first():
    order = fix_first(["a", "b", "kit"], {"a": {"kit"}, "b": {"kit"}})
    assert order == Order(["kit", "a", "b"], [])


def test_dependencies_of_one_repository_are_fixed_in_their_order():
    assert fix_first(["a", "b", "c"], {"a": {"c", "b"}}) == Order(["b", "c", "a"], [])


def test_repositories_that_depend_on_each_other_keep_their_order_and_are_reported():
    order = fix_first(["a", "b", "c", "d"], {"b": {"d"}, "d": {"b"}})
    assert order == Order(["a", "b", "d", "c"], [["b", "d"]])


def test_a_dependency_of_a_cycle_is_fixed_before_it():
    order = fix_first(["a", "b", "c"], {"a": {"b"}, "b": {"a", "c"}})
    assert order == Order(["c", "a", "b"], [["a", "b"]])
