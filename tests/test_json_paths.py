from __future__ import annotations

from src.domain.json_paths import safe_get


def test_safe_get_nested_dict():
    d = {"a": {"b": {"c": 42}}}
    assert safe_get(d, ["a", "b", "c"]) == 42


def test_safe_get_missing_key_returns_none():
    assert safe_get({"a": 1}, ["a", "b"]) is None


def test_safe_get_missing_key_returns_custom_default():
    assert safe_get({"a": 1}, ["x"], default=0) == 0


def test_safe_get_non_dict_in_path_returns_default():
    assert safe_get({"a": 5}, ["a", "b"]) is None


def test_safe_get_empty_path_returns_root():
    d = {"a": 1}
    assert safe_get(d, []) is d


def test_safe_get_none_value_is_returned():
    assert safe_get({"a": None}, ["a"]) is None


def test_safe_get_empty_dict():
    assert safe_get({}, ["missing"]) is None
