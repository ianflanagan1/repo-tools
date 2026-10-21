"""The plugins that come with repo-list and repo-fix."""

from repo_list.plugin import Plugin
from repo_list.plugins.detached import Detached
from repo_list.plugins.github import GitHub
from repo_list.plugins.init import Init
from repo_list.plugins.packagist import Packagist
from repo_list.plugins.stashes import Stashes
from repo_list.plugins.sync import Sync
from repo_list.plugins.uncommitted import Uncommitted


def built_in(
    packagist_vendor: str | None, init: bool = False, wait_for_ci: bool = True
) -> list[Plugin]:
    """The built-in plugins, in the order their problems are shown.

    Packagist is checked only given packagist_vendor, and a folder of files is made a repository
    only with init.
    """
    return [
        Init(fixes=init),
        GitHub(wait_for_ci=wait_for_ci),
        Uncommitted(),
        Sync(),
        Detached(),
        Stashes(),
        *([Packagist(packagist_vendor)] if packagist_vendor else []),
    ]
