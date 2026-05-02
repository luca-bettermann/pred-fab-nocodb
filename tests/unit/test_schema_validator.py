"""Tests for SchemaValidator."""
import pytest

from pred_fab_nocodb import SchemaMismatchError, SchemaValidator


def test_identical_schemas_have_no_diff():
    s = {"a": 1, "b": [1, 2, 3], "c": {"x": "y"}}
    assert SchemaValidator.diff(s, dict(s)) == []


def test_missing_top_level_key():
    expected = {"a": 1, "b": 2}
    actual = {"a": 1}
    diffs = SchemaValidator.diff(expected, actual)
    assert any("missing in actual" in d for d in diffs)


def test_extra_top_level_key():
    expected = {"a": 1}
    actual = {"a": 1, "b": 2}
    diffs = SchemaValidator.diff(expected, actual)
    assert any("extra in actual" in d for d in diffs)


def test_value_mismatch():
    expected = {"a": 1}
    actual = {"a": 2}
    diffs = SchemaValidator.diff(expected, actual)
    assert any("expected 1" in d and "got 2" in d for d in diffs)


def test_nested_mismatch_includes_path():
    expected = {"params": {"speed": {"low": 0.004, "high": 0.008}}}
    actual = {"params": {"speed": {"low": 0.004, "high": 0.010}}}
    diffs = SchemaValidator.diff(expected, actual)
    assert any("params.speed.high" in d for d in diffs)


def test_list_compared_order_insensitive():
    expected = {"items": [1, 2, 3]}
    actual = {"items": [3, 1, 2]}
    assert SchemaValidator.diff(expected, actual) == []


def test_list_with_dict_items():
    expected = {"params": [{"code": "a", "low": 0.0}, {"code": "b", "low": 1.0}]}
    actual = {"params": [{"code": "b", "low": 1.0}, {"code": "a", "low": 0.0}]}
    assert SchemaValidator.diff(expected, actual) == []


def test_assert_compatible_raises_on_mismatch():
    expected = {"a": 1}
    actual = {"a": 2}
    with pytest.raises(SchemaMismatchError) as exc:
        SchemaValidator.assert_compatible(expected, actual, study_code="S")
    assert exc.value.study_code == "S"
    assert exc.value.differences


def test_assert_compatible_raises_on_none_actual():
    """No schema in NocoDB → mismatch."""
    with pytest.raises(SchemaMismatchError):
        SchemaValidator.assert_compatible({"a": 1}, None, study_code="S")


def test_assert_compatible_silent_on_match():
    """Matching schemas → no error raised."""
    s = {"a": 1, "b": [1, 2]}
    SchemaValidator.assert_compatible(s, dict(s), study_code="S")
