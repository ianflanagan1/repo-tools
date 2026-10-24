"""A repo's one-line description: its manifest's, or else one a language model writes from its
tracked files.

Only files git tracks are read or listed, so nothing ignored or untracked, such as a .env,
reaches the model. Which model writes it is the small model of the provider set in config.toml.
"""

from pathlib import Path

from cli_kit import models
from cli_kit.models import Model
from cli_kit.proc import output

from repo_list import config
from repo_tools import manifest
from repo_tools.description.prompt import description, prompt

# Top-level files that say what a project is, matched ignoring case.
DOCUMENTS = {
    "readme",
    "readme.md",
    "readme.rst",
    "readme.txt",
    "claude.md",
    "agents.md",
    "composer.json",
    "package.json",
    "cargo.toml",
    "pyproject.toml",
    "go.mod",
    "pom.xml",
}


def configured_model() -> Model | None:
    """The small model of the provider set in config.toml, or None when it's none."""
    provider = config.load().description_provider
    return None if provider is None else models.small(provider)


def for_new_repo(directory: Path, name: str, model: Model | None, max_length: int) -> str:
    """The description to create the repo in directory, called name, with: its manifest's,
    else one model writes, which it prints, else "". None for model writes none."""
    if text := manifest.description(directory):
        return text
    generated = None if model is None else generate(directory, name, model, max_length)
    if generated is None:
        return ""
    print(f"Generated its description: {generated}")
    return generated


def generate(directory: Path, name: str, model: Model, max_length: int) -> str | None:
    """The description model writes for the repo in directory, called name, or None when it
    has no tracked files or the model gives no usable reply."""
    files = output("git", "-C", str(directory), "ls-files", "-z").split("\0")
    files = [path for path in files if path]
    documents = {
        path: (directory / path).read_text(errors="replace")
        for path in files
        if "/" not in path and path.lower() in DOCUMENTS and (directory / path).is_file()
    }
    asked = prompt(name, files, documents, max_length)
    if asked is None:
        return None
    reply = model.reply(asked)
    return None if reply is None else description(reply, max_length)
