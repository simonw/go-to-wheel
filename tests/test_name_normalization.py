"""Tests for PEP 427 name normalization in wheel filenames."""

from go_to_wheel import normalize_package_name


def test_normalize_package_name_collapses_separator_runs():
    # PEP 427: any run of -_. characters becomes a single underscore
    assert normalize_package_name("my--tool") == "my_tool"
    assert normalize_package_name("my..tool") == "my_tool"
    assert normalize_package_name("my-._tool") == "my_tool"


def test_normalize_package_name_simple_cases_unchanged():
    assert normalize_package_name("my-test-tool") == "my_test_tool"
    assert normalize_package_name("My.Tool") == "my_tool"
