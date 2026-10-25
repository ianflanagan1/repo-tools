"""The plugins that come with repo-list and repo-fix."""

from collections.abc import Set

from cli_kit.models.agent import Announce
from cli_kit.models.claude_code import ClaudeCode

from repo_list import hosts
from repo_list.plugin import Plugin
from repo_list.plugins.branch import Branch
from repo_list.plugins.detached import Detached
from repo_list.plugins.github import GitHub
from repo_list.plugins.init import Init
from repo_list.plugins.npm import Npm
from repo_list.plugins.package import Package
from repo_list.plugins.packagist import Packagist
from repo_list.plugins.proposal import Proposal
from repo_list.plugins.remote import Remote
from repo_list.plugins.stashes import Stashes
from repo_list.plugins.sync import Sync
from repo_list.plugins.uncommitted import COMMIT_TIMEOUT_SECONDS, Uncommitted
from repo_tools.packages import Name


def built_in(
    packagist_vendor: str | None,
    npm_scope: str | None,
    pinned: Set[Name],
    announce: Announce,
    init: bool = False,
    wait_for_ci: bool = True,
) -> list[Plugin]:
    """The built-in plugins, in the order their problems are shown.

    Packagist is checked only given packagist_vendor, npm only given npm_scope, and a directory of
    files is made a repository only with init. pinned is every name the directories pin, which
    makes a Python project a package. announce shows each run of an agent, such as the
    commit skill's, as it starts.
    """
    return [
        Init(fixes=init),
        GitHub(wait_for_ci=wait_for_ci),
        Uncommitted(ClaudeCode(None, COMMIT_TIMEOUT_SECONDS, announce)),
        Sync(),
        Proposal(hosts.for_remote),
        Branch(),
        Remote(hosts.for_remote),
        Package(pinned),
        Detached(),
        Stashes(),
        *([Packagist(packagist_vendor)] if packagist_vendor else []),
        *([Npm(npm_scope)] if npm_scope else []),
    ]
