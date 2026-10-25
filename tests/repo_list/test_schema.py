"""The schema of a repository's .config/ianf-repo-tools.toml, for editors to check it against."""

import json
import re
import tomllib
from pathlib import Path

import jsonschema

from repo_list.integration import Integration

ROOT = Path(__file__).parent.parent.parent
SCHEMA = ROOT / "schema" / "ianf-repo-tools.v1.json"


def test_the_schema_offers_every_integration():
    schema = json.loads(SCHEMA.read_text())
    assert schema["properties"]["integration"]["enum"] == list(Integration)


def test_the_readme_s_example_names_the_schema_and_meets_it():
    readme = (ROOT / "README.md").read_text()
    example = re.search(r"```toml\n(#:schema .*?)```", readme, re.DOTALL)
    assert example
    schema = json.loads(SCHEMA.read_text())
    assert example[1].splitlines()[0] == f"#:schema {schema['$id']}"
    jsonschema.validate(tomllib.loads(example[1]), schema)
