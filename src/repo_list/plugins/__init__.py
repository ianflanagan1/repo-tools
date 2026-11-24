"""The plugins that come with repo-list and repo-fix."""

from collections.abc import Mapping, Sequence, Set
from pathlib import Path
from typing import assert_never

from cli_kit.models.agent import Announce
from cli_kit.models.claude_code import ClaudeCode

from repo_list import remote_repos
from repo_list.config import Config
from repo_list.plugin import Plugin
from repo_list.plugins.branch import Branch
from repo_list.plugins.dependants import Dependants
from repo_list.plugins.dependency import Dependency
from repo_list.plugins.detached import Detached
from repo_list.plugins.init import Init
from repo_list.plugins.lock import Lock
from repo_list.plugins.npm import Npm
from repo_list.plugins.packagist import Packagist
from repo_list.plugins.proposal import Proposal
from repo_list.plugins.publish import Publish
from repo_list.plugins.release import Release
from repo_list.plugins.remote import Remote
from repo_list.plugins.stashes import Stashes
from repo_list.plugins.sync import Sync
from repo_list.plugins.uncommitted import COMMIT_TIMEOUT_SECONDS, Uncommitted
from repo_tools.dependencies import Ecosystem, Name


def built_in(
    chosen: Set[Ecosystem],
    settings: Config,
    pinned: Set[Name],
    offering: Set[Path],
    providers: Mapping[Name, Path],
    announce: Announce,
    *,
    upgrade_locks: bool,
    own_go_modules: Sequence[str],
    init: bool = False,
    wait_for_ci: bool = True,
) -> list[Plugin]:
    """The built-in plugins, in the order their problems are shown.

    The packages of yours in each ecosystem chosen are released, published in its registry, and
    reported where a lock file holds one at less than its latest; settings say which are yours.
    Lock files are upgraded in full, and what they hold installed, only with upgrade_locks; the
    upgrade asks the repository of each of own_go_modules, the Go modules here, for it directly.
    A directory of files is made a repository only with init. pinned is every name the
    directories pin, which makes a Python project a package, offering every directory whose flake
    has an output for other flakes, which makes it one, and providers the repository each package
    of yours comes from. announce shows each run of an agent, such as the commit skill's,
    as it starts.
    """
    ordered = [e for e in Ecosystem if e in chosen]
    return [
        Init(fixes=init),
        Publish(wait_for_ci=wait_for_ci),
        Uncommitted(ClaudeCode(None, COMMIT_TIMEOUT_SECONDS, announce)),
        Sync(),
        Proposal(remote_repos.for_remote),
        Branch(),
        Remote(remote_repos.for_remote),
        Dependency(pinned, offering),
        Detached(),
        Stashes(),
        *([Lock(own_go_modules)] if upgrade_locks else []),
        *(
            [Dependants(chosen, providers), Release(chosen, settings, pinned, offering)]
            if chosen
            else []
        ),
        *(plugin for ecosystem in ordered for plugin in registry(ecosystem, settings)),
    ]


def registry(ecosystem: Ecosystem, settings: Config) -> list[Plugin]:
    """The plugins that publish the ecosystem's packages of yours in its registry, and wait for
    it to have what was released: none for one with no registry, as Python's and Nix's pinned from
    git, or Go's, whose module proxy fetches each version tag the first time it's asked for."""
    match ecosystem:
        case Ecosystem.COMPOSER:
            vendor = settings.packagist_vendor
            return [Packagist(vendor)] if vendor else []
        case Ecosystem.NPM:
            scope = settings.npm_scope
            return [Npm(scope)] if scope else []
        case Ecosystem.PYTHON | Ecosystem.GO | Ecosystem.NIX:
            return []
        case _:
            assert_never(ecosystem)
