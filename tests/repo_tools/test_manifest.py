from pathlib import Path

from repo_tools.manifest import composer_name, description


def test_reads_the_description_from_composer_json(tmp_path: Path):
    (tmp_path / "composer.json").write_text('{"name": "a/b", "description": "A PHP package"}')
    assert description(tmp_path) == "A PHP package"


def test_reads_the_description_from_package_json(tmp_path: Path):
    (tmp_path / "package.json").write_text('{"name": "b", "description": "A Node package"}')
    assert description(tmp_path) == "A Node package"


def test_reads_the_package_description_from_cargo_toml(tmp_path: Path):
    (tmp_path / "Cargo.toml").write_text('[package]\nname = "b"\ndescription = "A Rust crate"\n')
    assert description(tmp_path) == "A Rust crate"


def test_reads_a_workspace_package_description_from_cargo_toml(tmp_path: Path):
    (tmp_path / "Cargo.toml").write_text('[workspace.package]\ndescription = "A Rust workspace"\n')
    assert description(tmp_path) == "A Rust workspace"


def test_reads_the_project_description_from_pyproject_toml(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "b"\ndescription = "A Python project"\n'
    )
    assert description(tmp_path) == "A Python project"


def test_reads_a_poetry_description_from_pyproject_toml(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        '[tool.poetry]\nname = "b"\ndescription = "A Poetry project"\n'
    )
    assert description(tmp_path) == "A Poetry project"


def test_reads_the_description_from_a_namespaced_pom_xml(tmp_path: Path):
    (tmp_path / "pom.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<project xmlns="http://maven.apache.org/POM/4.0.0">\n'
        "  <artifactId>b</artifactId>\n"
        "  <description>A Maven project</description>\n"
        "</project>\n"
    )
    assert description(tmp_path) == "A Maven project"


def test_ignores_a_nested_description_in_pom_xml(tmp_path: Path):
    (tmp_path / "pom.xml").write_text(
        "<project><licenses><license><description>MIT</description></license></licenses></project>"
    )
    assert description(tmp_path) == ""


def test_reads_the_description_from_any_property_group_of_a_csproj(tmp_path: Path):
    (tmp_path / "Tool.csproj").write_text(
        '<Project Sdk="Microsoft.NET.Sdk">\n'
        "  <PropertyGroup><TargetFramework>net8.0</TargetFramework></PropertyGroup>\n"
        "  <PropertyGroup><Description>A .NET project</Description></PropertyGroup>\n"
        "</Project>\n"
    )
    assert description(tmp_path) == "A .NET project"


def test_reads_the_summary_from_a_gemspec_in_either_quote_style(tmp_path: Path):
    gemspec = tmp_path / "b.gemspec"
    gemspec.write_text('Gem::Specification.new do |spec|\n  spec.summary = "A Ruby gem"\nend\n')
    assert description(tmp_path) == "A Ruby gem"
    gemspec.write_text("Gem::Specification.new do |s|\n  s.summary     = 'A Ruby gem'\nend\n")
    assert description(tmp_path) == "A Ruby gem"


def test_keeps_colons_and_quotes_in_a_toml_or_xml_description(tmp_path: Path):
    cargo = tmp_path / "Cargo.toml"
    cargo.write_text('[package]\ndescription = "Tool: does \\"things\\" fast"\n')
    assert description(tmp_path) == 'Tool: does "things" fast'
    cargo.unlink()
    (tmp_path / "pom.xml").write_text(
        '<project><description>Tool: does "things" fast</description></project>\n'
    )
    assert description(tmp_path) == 'Tool: does "things" fast'


def test_uses_only_the_first_line_of_a_multi_line_description(tmp_path: Path):
    (tmp_path / "composer.json").write_text('{"description": "First line\\nSecond line"}')
    assert description(tmp_path) == "First line"


def test_prefers_composer_json_over_other_manifests(tmp_path: Path):
    (tmp_path / "composer.json").write_text('{"description": "From composer"}')
    (tmp_path / "package.json").write_text('{"description": "From package"}')
    assert description(tmp_path) == "From composer"


def test_skips_a_manifest_without_a_description(tmp_path: Path):
    (tmp_path / "composer.json").write_text('{"name": "a/b"}')
    (tmp_path / "package.json").write_text('{"description": "From package"}')
    assert description(tmp_path) == "From package"


def test_is_empty_without_a_manifest(tmp_path: Path):
    assert description(tmp_path) == ""


def test_is_empty_for_a_manifest_it_cannot_parse(tmp_path: Path):
    (tmp_path / "composer.json").write_text("not json")
    (tmp_path / "Cargo.toml").write_text("[package")
    (tmp_path / "pom.xml").write_text("<project>")
    assert description(tmp_path) == ""


def test_reads_the_composer_package_name(tmp_path):
    (tmp_path / "composer.json").write_text('{"name": "me/thing"}')
    assert composer_name(tmp_path) == "me/thing"


def test_a_project_without_a_composer_package_name_has_none(tmp_path):
    assert composer_name(tmp_path) is None
    (tmp_path / "composer.json").write_text('{"description": "no name"}')
    assert composer_name(tmp_path) is None
