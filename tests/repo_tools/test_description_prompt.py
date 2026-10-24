from repo_tools.description.prompt import MAX_DOCUMENT_CHARACTERS, MAX_FILES, description, prompt


def test_the_prompt_states_the_length_limit():
    text = prompt("thing", ["README.md"], {}, 350)
    assert "At most 350 characters" in text


def test_the_prompt_names_the_repository_and_lists_its_files():
    text = prompt("thing", ["README.md", "src/main.py"], {}, 350)
    assert "Repository: thing" in text
    assert "README.md\nsrc/main.py" in text


def test_the_prompt_includes_each_document_under_its_path():
    text = prompt("thing", ["README.md"], {"README.md": "# Thing\nDoes things."}, 350)
    assert "--- README.md ---\n# Thing\nDoes things." in text


def test_a_long_document_is_cut_short():
    long = "x" * (MAX_DOCUMENT_CHARACTERS + 10)
    text = prompt("thing", ["README.md"], {"README.md": long}, 350)
    assert "x" * MAX_DOCUMENT_CHARACTERS in text
    assert "x" * (MAX_DOCUMENT_CHARACTERS + 1) not in text


def test_a_long_file_list_is_cut_short_and_says_how_many_were_left_out():
    files = [f"f{i}" for i in range(MAX_FILES + 5)]
    text = prompt("thing", files, {}, 350)
    assert f"f{MAX_FILES - 1}\n" in text
    assert f"f{MAX_FILES}\n" not in text
    assert "(and 5 more)" in text


def test_a_repository_with_no_files_has_nothing_to_describe():
    assert prompt("thing", [], {}, 350) is None


def test_a_reply_is_trimmed_to_one_line():
    assert description("  A tool\nfor  things.\n", 350) == "A tool for things."


def test_quotes_around_a_reply_are_removed():
    assert description('"A tool for things."', 350) == "A tool for things."
    assert description("`'A tool for things.'`", 350) == "A tool for things."


def test_a_reply_at_the_limit_is_kept():
    assert description("x" * 350, 350) == "x" * 350


def test_a_reply_over_the_limit_is_rejected():
    assert description("x" * 351, 350) is None


def test_an_empty_reply_is_rejected():
    assert description(' " ', 350) is None
