"""📁 A directory of files in no repository, made one with `git init` when asked."""

from dataclasses import dataclass

from repo_list.git import git
from repo_list.plugin import Log, Plugin, Problem, Stage
from repo_list.scan import Directory


@dataclass(frozen=True)
class NotARepo:
    """A directory of files in no repository."""

    def describe(self) -> str:
        return "📁 not a git repository"


class Init(Plugin):
    name = "init"
    checks_directories = True

    def __init__(self, fixes: bool) -> None:
        """With fixes, each directory of files is made a repository; otherwise it's only
        reported."""
        self.stage = Stage.INIT if fixes else None

    def check(self, directory: Directory) -> list[Problem]:
        return [] if directory.is_repo else [NotARepo()]

    def fix(self, directory: Directory, problems: list[Problem], log: Log) -> bool:
        git(directory.path, "init", "-q")
        directory.is_repo = True
        log(True, "Initialised a git repository")
        return True
