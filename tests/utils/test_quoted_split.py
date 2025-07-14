import pytest

from ynab_unlinked.utils import split_quoted_string


@pytest.mark.parametrize(
    "input_string, expected_output",
    [
        # Cases without quotes
        pytest.param("this is my name", ["this", "is", "my", "name"], id="no_quotes_basic"),
        pytest.param("simple test string", ["simple", "test", "string"], id="no_quotes_simple"),
        pytest.param("singleword", ["singleword"], id="no_quotes_single_word"),
        pytest.param("", [], id="empty_string"),  # Empty string
        pytest.param(
            "   multiple   spaces   ", ["multiple", "spaces"], id="no_quotes_multi_spaces"
        ),  # Leading/trailing/multiple internal spaces
        pytest.param("  ", [], id="only_spaces"),  # Only spaces
        # Cases with single quotes
        pytest.param(
            "I live in 'La guardia'", ["I", "live", "in", "La guardia"], id="single_quotes_basic"
        ),
        pytest.param(
            "'quoted phrase' at start",
            ["quoted phrase", "at", "start"],
            id="single_quotes_at_start",
        ),
        pytest.param(
            "end with 'another one'", ["end", "with", "another one"], id="single_quotes_at_end"
        ),
        pytest.param(
            "middle 'quoted part' here",
            ["middle", "quoted part", "here"],
            id="single_quotes_in_middle",
        ),
        pytest.param("'single'", ["single"], id="single_quotes_only_word"),
        pytest.param(
            "two 'quoted' 'parts'", ["two", "quoted", "parts"], id="single_quotes_multiple"
        ),
        pytest.param("''", [], id="single_quotes_empty"),  # Empty single quoted string
        # Cases with double quotes
        pytest.param(
            'Hello, "World Wide Web" is great!',
            ["Hello,", "World Wide Web", "is", "great!"],
            id="double_quotes_basic",
        ),
        pytest.param(
            '"double quoted" example', ["double quoted", "example"], id="double_quotes_at_start"
        ),
        pytest.param(
            'another "test case" here',
            ["another", "test case", "here"],
            id="double_quotes_in_middle",
        ),
        pytest.param('""', [], id="double_quotes_empty"),  # Empty double quoted string
        # Cases with backticks
        pytest.param(
            "Path is `/usr/local/bin`", ["Path", "is", "/usr/local/bin"], id="backticks_basic"
        ),
        pytest.param(
            "command `ls -la /tmp` to list",
            ["command", "ls -la /tmp", "to", "list"],
            id="backticks_command_example",
        ),
        pytest.param("``", [], id="backticks_empty"),  # Empty backtick string
        # Mixed quotes and complex cases
        pytest.param(
            "Mixed 'quotes and' \"other things\" `like this`",
            ["Mixed", "quotes and", "other things", "like this"],
            id="mixed_quotes",
        ),
        pytest.param(
            "Text with 'single quotes' and \"double quotes\" in it",
            ["Text", "with", "single quotes", "and", "double quotes", "in", "it"],
            id="mixed_types_of_quotes",
        ),
        pytest.param(
            'Path: `/usr/bin/python` Version: "3.9.7"',
            ["Path:", "/usr/bin/python", "Version:", "3.9.7"],
            id="mixed_quotes_with_punctuation",
        ),
        pytest.param(
            "A string with \"empty\" and '' quotes",
            ["A", "string", "with", "empty", "and", "quotes"],
            id="mixed_empty_quotes",
        ),
    ],
)
def test_split_quoted_string(input_string: str, expected_output: list[str]):
    actual_output = split_quoted_string(input_string)
    assert actual_output == expected_output, (
        f"For input: '{input_string}', Expected: {expected_output}, Got: {actual_output}"
    )
