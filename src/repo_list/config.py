"""Settings from the project's config.toml.

The file is gitignored, so each clone keeps its own settings out of the repository, as a PHP
project keeps its .env; config.example.toml shows them. A missing file, or a setting left out,
takes its default.
"""

import argparse
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from cli_kit.models import Provider

NO_PROVIDER = "none"

# The project root: .venv's parent, as `uv sync` builds it there.
CONFIG = Path(sys.prefix).parent / "config.toml"


@dataclass(frozen=True)
class Config:
    root: str = "~/projects"
    """Where repo-list and repo-fix look when given no folder."""
    packagist_vendor: str | None = None
    """The vendor whose packages should be on Packagist; None checks no packages."""
    bitbucket_workspace: str | None = None
    """The Bitbucket workspace a repo given by bare name is in; None means one must be named."""
    description_provider: Provider | None = Provider.CLAUDE
    """Who writes a new GitHub or Bitbucket repo's description when its manifest has none; None
    for no one."""


class ConfigError(Exception):
    """config.toml can't be read as settings. The message names the file and what's wrong."""


def load(path: Path | None = None) -> Config:
    """The settings in path, by default the project's config.toml."""
    path = path or CONFIG
    try:
        settings = tomllib.loads(path.read_text())
    except FileNotFoundError:
        return Config()
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{path}: {error}") from None

    packagist = settings.pop("packagist", {})
    if not isinstance(packagist, dict):
        raise ConfigError(f"{path}: packagist must be a table")
    bitbucket = settings.pop("bitbucket", {})
    if not isinstance(bitbucket, dict):
        raise ConfigError(f"{path}: bitbucket must be a table")
    description = settings.pop("description", {})
    if not isinstance(description, dict):
        raise ConfigError(f"{path}: description must be a table")
    unknown = [
        *settings.keys() - {"root"},
        *(f"packagist.{k}" for k in packagist.keys() - {"vendor"}),
        *(f"bitbucket.{k}" for k in bitbucket.keys() - {"workspace"}),
        *(f"description.{k}" for k in description.keys() - {"provider"}),
    ]
    if unknown:
        raise ConfigError(f"{path}: unknown setting {', '.join(sorted(unknown))}")

    root = settings.get("root", Config.root)
    vendor = packagist.get("vendor", Config.packagist_vendor)
    if not isinstance(root, str):
        raise ConfigError(f"{path}: root must be a string")
    if vendor is not None and not isinstance(vendor, str):
        raise ConfigError(f"{path}: packagist.vendor must be a string")
    workspace = bitbucket.get("workspace", Config.bitbucket_workspace)
    if workspace is not None and not isinstance(workspace, str):
        raise ConfigError(f"{path}: bitbucket.workspace must be a string")
    provider = description.get("provider", Config.description_provider)
    if provider != NO_PROVIDER and provider not in set(Provider):
        choices = ", ".join([*Provider, NO_PROVIDER])
        raise ConfigError(f"{path}: description.provider must be one of {choices}")
    return Config(
        root,
        vendor,
        workspace,
        None if provider == NO_PROVIDER else Provider(provider),
    )


def for_command(parser: argparse.ArgumentParser, packagist: bool) -> Config:
    """The settings for a command that parser parsed, ending it with a usage error when they
    can't be read, or when packagist is asked for with no vendor to check."""
    try:
        settings = load()
    except ConfigError as error:
        parser.error(str(error))
    if packagist and not settings.packagist_vendor:
        parser.error(
            f"--packagist needs your vendor name: set packagist.vendor in {CONFIG}, "
            f"as {CONFIG.with_name('config.example.toml').name} shows"
        )
    return settings
