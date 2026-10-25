"""The order repo-fix takes repositories in, so that each one's pinned dependencies among them are
fixed before it, and pushed by the time it is, ready for its lock file to be updated.

Only pinned dependencies count, as repo_tools.packages says: one read from a path is seen as it
is on disk, so fixing it first changes nothing for its dependant.
"""

from collections.abc import Collection, Hashable, Mapping, Sequence, Set
from dataclasses import dataclass

from repo_tools.packages import Name


@dataclass(frozen=True)
class Order[K]:
    keys: list[K]
    """Every key, each after those it depends on but for a cycle's."""
    cycles: list[list[K]]
    """Each set of keys that depend on each other, in their given order, as they are fixed."""


def edges[K: Hashable](
    called: Mapping[K, Set[Name]], pins: Mapping[K, Set[Name]]
) -> dict[K, set[K]]:
    """What each key depends on, given what each is called and what each pins: those whose name it
    pins, but never itself."""
    by_name: dict[Name, set[K]] = {}
    for key, names in called.items():
        for name in names:
            by_name.setdefault(name, set()).add(key)
    return {
        key: {other for name in pins.get(key, set()) for other in by_name.get(name, set())} - {key}
        for key in called
    }


def fix_first[K: Hashable](keys: Sequence[K], depends_on: Mapping[K, Collection[K]]) -> Order[K]:
    """keys, in their order but with each one's dependencies moved before it, theirs before them,
    and so on. Keys that depend on each other, directly or through others, keep their order
    among themselves, after whatever any of them depends on."""
    place = {key: i for i, key in enumerate(keys)}
    index: dict[K, int] = {}
    low: dict[K, int] = {}
    stack: list[K] = []
    order: Order[K] = Order([], [])

    # Tarjan's algorithm, which finishes each set of keys that depend on each other after every
    # set they depend on, so finishing order is fixing order.
    def visit(key: K) -> None:
        index[key] = low[key] = len(index)
        stack.append(key)
        for dependency in sorted(
            (d for d in depends_on.get(key, ()) if d in place), key=place.__getitem__
        ):
            if dependency not in index:
                visit(dependency)
                low[key] = min(low[key], low[dependency])
            elif dependency in stack:
                low[key] = min(low[key], index[dependency])
        if low[key] == index[key]:
            members = stack[stack.index(key) :]
            del stack[stack.index(key) :]
            members.sort(key=place.__getitem__)
            order.keys.extend(members)
            if len(members) > 1:
                order.cycles.append(members)

    for key in keys:
        if key not in index:
            visit(key)
    return order
