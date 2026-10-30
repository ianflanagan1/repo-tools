"""Settings from the project's config.toml.

The file is gitignored, so each clone keeps its own settings out of the repository, as a PHP
project keeps its .env; config.example.toml shows them. A missing file, or a setting left out,
takes its default.
"""

import sys
import tomllib
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import final

from cli_kit.models import Provider

from repo_list.integration import Integration

NO_PROVIDER = "none"

# The project root: .venv's parent, as `uv sync` builds it there.
CONFIG = Path(sys.prefix).parent / "config.toml"


@dataclass(frozen=True)
class Config:
    root: str = "~/projects"
    """Where repo-list and repo-fix look when given no directory."""
    packagist_vendor: str | None = None
    """The vendor whose packages should be on Packagist; None checks no packages."""
    bitbucket_workspace: str | None = None
    """The Bitbucket workspace a repo given by bare name is in; None means one must be named."""
    description_provider: Provider | None = Provider.CLAUDE
    """Who writes a new GitHub or Bitbucket repo's description when its manifest has none; None
    for no one."""
    npm_scope: str | None = None
    """The npm scope, such as @me, whose packages should be on npm; None checks no packages."""


@final
@dataclass(frozen=True)
class Invalid:
    """A setting that can't be used, and why."""

    message: str


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
    npm = settings.pop("npm", {})
    if not isinstance(npm, dict):
        raise ConfigError(f"{path}: npm must be a table")
    unknown = [
        *settings.keys() - {"root"},
        *(f"packagist.{k}" for k in packagist.keys() - {"vendor"}),
        *(f"bitbucket.{k}" for k in bitbucket.keys() - {"workspace"}),
        *(f"description.{k}" for k in description.keys() - {"provider"}),
        *(f"npm.{k}" for k in npm.keys() - {"scope"}),
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
    scope = npm.get("scope", Config.npm_scope)
    if scope is not None and not (isinstance(scope, str) and scope.startswith("@")):
        raise ConfigError(f"{path}: npm.scope must start with @, such as @me")
    return Config(
        root,
        vendor,
        workspace,
        None if provider == NO_PROVIDER else Provider(provider),
        scope,
    )


class Version(IntEnum):
    """The versions of a repository's .config/ianf-repo-tools.toml repo-tools reads."""

    V1 = 1


SCHEMA = (
    "https://raw.githubusercontent.com/ianflanagan1/repo-tools/main/schema/ianf-repo-tools.v1.json"
)
"""The JSON Schema of the version of .config/ianf-repo-tools.toml repo-tools writes."""


def integration_in(table: dict, where: str) -> Integration | Invalid | None:
    """The integration table names, None when it names none, or what's wrong with it.

    where says where the setting is, for the message, such as
    ".config/ianf-repo-tools.toml: integration". There's no default: a guess would push or
    rewrite the wrong things.
    """
    integration = table.get("integration")
    if integration is None:
        return None
    if integration not in set(Integration):
        return Invalid(f"{where} must be one of {', '.join(Integration)}")
    return Integration(integration)


def skip_fix_in(table: dict, where: str) -> bool | Invalid:
    """Whether table asks repo-fix to leave the repository alone, false when it doesn't say, or
    what's wrong with it.

    where says where the setting is, for the message, such as
    ".config/ianf-repo-tools.toml: skip-fix".
    """
    skip_fix = table.get("skip-fix", False)
    if not isinstance(skip_fix, bool):
        return Invalid(f"{where} must be true or false")
    return skip_fix
