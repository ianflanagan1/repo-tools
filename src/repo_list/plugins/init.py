"""📁 A folder of files in no repository, made one with `git init` when asked."""

from dataclasses import dataclass

from repo_list.git import git
from repo_list.plugin import Log, Plugin, Problem, Stage
from repo_list.scan import Folder


@dataclass(frozen=True)
class NotARepo:
    """A folder of files in no repository."""

    def describe(self) -> str:
        return "📁 not a git repository"


class Init(Plugin):
    name = "init"
    checks_folders = True

    def __init__(self, fixes: bool) -> None:
        """With fixes, each folder of files is made a repository; otherwise it's only reported."""
        self.stage = Stage.INIT if fixes else None

    def check(self, folder: Folder) -> list[Problem]:
        return [] if folder.is_repo else [NotARepo()]

    def fix(self, folder: Folder, problems: list[Problem], log: Log) -> bool:
        git(folder.path, "init", "-q")
        folder.is_repo = True
        log(True, "Initialised a git repository")
        return True
