"""Behaviour of the settings read from the project's config.toml."""

import sys
from pathlib import Path

import pytest
from cli_kit.models import Provider

from repo_list import config
from repo_list.config import Config


@pytest.fixture
def file(tmp_path: Path) -> Path:
    return tmp_path / "settings.toml"


def test_without_a_config_file_every_setting_takes_its_default(file):
    assert config.load(file) == Config(root="~/projects", packagist_vendor=None)


def test_the_root_and_packagist_vendor_are_read_from_the_file(file):
    file.write_text('root = "~/code"\n\n[packagist]\nvendor = "me"\n')
    assert config.load(file) == Config(root="~/code", packagist_vendor="me")


def test_a_setting_left_out_takes_its_default(file):
    file.write_text('[packagist]\nvendor = "me"\n')
    assert config.load(file) == Config(root="~/projects", packagist_vendor="me")


def test_a_file_that_is_not_toml_is_an_error_naming_the_file(file):
    file.write_text("root = \n")
    with pytest.raises(config.ConfigError, match=f"^{file}: "):
        config.load(file)


def test_a_setting_of_the_wrong_type_is_an_error_naming_it(file):
    file.write_text("[packagist]\nvendor = 1\n")
    with pytest.raises(config.ConfigError, match="packagist.vendor must be a string"):
        config.load(file)


def test_an_unknown_setting_is_an_error_naming_it(file):
    file.write_text('rot = "~/code"\n')
    with pytest.raises(config.ConfigError, match="unknown setting rot"):
        config.load(file)


def test_the_bitbucket_workspace_is_read_from_the_file(file):
    file.write_text('[bitbucket]\nworkspace = "team"\n')
    assert config.load(file).bitbucket_workspace == "team"


def test_without_a_bitbucket_workspace_none_is_set(file):
    file.write_text('root = "~/code"\n')
    assert config.load(file).bitbucket_workspace is None


def test_an_unknown_bitbucket_setting_is_an_error_naming_it(file):
    file.write_text('[bitbucket]\nworkspce = "team"\n')
    with pytest.raises(config.ConfigError, match="unknown setting bitbucket.workspce"):
        config.load(file)


def test_without_a_description_provider_claude_writes_descriptions(file):
    file.write_text('root = "~/code"\n')
    assert config.load(file).description_provider is Provider.CLAUDE


def test_the_description_provider_is_read_from_the_file(file):
    file.write_text('[description]\nprovider = "gemini"\n')
    assert config.load(file).description_provider is Provider.GEMINI


def test_the_description_provider_none_means_no_one_writes_descriptions(file):
    file.write_text('[description]\nprovider = "none"\n')
    assert config.load(file).description_provider is None


def test_an_unknown_description_provider_is_an_error_naming_the_choices(file):
    file.write_text('[description]\nprovider = "eliza"\n')
    with pytest.raises(
        config.ConfigError,
        match="description.provider must be one of claude, openai, gemini, mistral, none",
    ):
        config.load(file)


def test_an_unknown_description_setting_is_an_error_naming_it(file):
    file.write_text('[description]\nmodel = "claude"\n')
    with pytest.raises(config.ConfigError, match="unknown setting description.model"):
        config.load(file)


def test_the_example_config_is_valid_and_names_placeholders():
    example = Path(sys.prefix).parent / "config.example.toml"
    assert config.load(example) == Config(
        root="~/projects", packagist_vendor="your-vendor", bitbucket_workspace="your-workspace"
    )
