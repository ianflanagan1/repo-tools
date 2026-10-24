"""What npmjs reads from npm: its trust configurations and the versions it still lacks."""

from repo_tools.npmjs import api


def test_a_scoped_package_name_is_escaped_for_the_registry():
    assert api.escaped("@me/thing") == "@me%2fthing"


def test_an_unscoped_package_name_is_left_as_it_is():
    assert api.escaped("thing") == "thing"


def test_each_trust_configuration_npm_prints_is_read():
    printed = (
        "\n"
        '{\n  "id": "a1",\n  "type": "github",\n  "file": "publish.yml",\n'
        '  "repository": "me/thing",\n  "permissions": ["createPackage"]\n}\n'
        "\n"
        '{\n  "id": "b2",\n  "type": "gitlab",\n  "file": "ci.yml"\n}\n'
    )
    assert api.parse_trusts(printed) == [
        {
            "id": "a1",
            "type": "github",
            "file": "publish.yml",
            "repository": "me/thing",
            "permissions": ["createPackage"],
        },
        {"id": "b2", "type": "gitlab", "file": "ci.yml"},
    ]


def test_a_one_time_password_prompt_around_the_configurations_is_ignored():
    printed = 'This operation requires a one-time password.\nEnter OTP: 123456\n{"id": "a1"}\n'
    assert api.parse_trusts(printed) == [{"id": "a1"}]


def test_no_configurations_print_nothing_and_read_as_none():
    assert api.parse_trusts("") == []


def test_the_publish_workflow_of_the_repo_is_trusted():
    configs = [{"type": "github", "file": "publish.yml", "repository": "Me/Thing"}]
    assert api.trusts_workflow(configs, "me/thing")


def test_the_publish_workflow_trusted_to_publish_is_trusted():
    configs = [
        {
            "type": "github",
            "file": "publish.yml",
            "repository": "me/thing",
            "permissions": ["createPackage"],
        }
    ]
    assert api.trusts_workflow(configs, "me/thing")


def test_a_workflow_trusted_only_to_stage_publishes_is_not_trusted():
    configs = [
        {
            "type": "github",
            "file": "publish.yml",
            "repository": "me/thing",
            "permissions": ["createStagedPackage"],
        }
    ]
    assert not api.trusts_workflow(configs, "me/thing")


def test_another_workflow_or_repo_is_not_trusted():
    configs = [
        {"type": "github", "file": "release.yml", "repository": "me/thing"},
        {"type": "github", "file": "publish.yml", "repository": "me/other"},
        {"type": "gitlab", "file": "publish.yml", "repository": "me/thing"},
    ]
    assert not api.trusts_workflow(configs, "me/thing")


def test_version_tags_npm_lacks_are_missing_oldest_first():
    tags = ["v0.3.0", "v0.1.0", "v0.2.0"]
    assert api.missing(tags, frozenset({"0.1.0"})) == ["v0.2.0", "v0.3.0"]


def test_version_tags_without_a_v_are_matched_too():
    assert api.missing(["0.1.0", "0.2.0"], frozenset({"0.1.0"})) == ["0.2.0"]


def test_tags_older_than_the_package_on_npm_are_not_missing():
    assert api.missing(["v0.1.0", "v0.2.0", "v0.3.0"], frozenset({"0.2.0"})) == ["v0.3.0"]


def test_tags_that_are_not_versions_are_not_missing():
    assert api.missing(["latest", "v2.0.0-beta1", "v0.1.0"], frozenset({"0.1.0"})) == []
