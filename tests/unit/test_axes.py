"""Tests for axes canonicalisation."""
from pred_fab_nocodb._axes import canonicalize_axes


def test_canonicalize_empty_axes():
    """Empty axes → empty JSON object."""
    assert canonicalize_axes({}) == "{}"


def test_canonicalize_single_axis():
    """Single key/value pair."""
    assert canonicalize_axes({"layer_idx": 3}) == '{"layer_idx":3}'


def test_canonicalize_sorts_keys():
    """Keys are sorted regardless of insertion order — required for UNIQUE."""
    a = canonicalize_axes({"layer_idx": 3, "node_idx": 2})
    b = canonicalize_axes({"node_idx": 2, "layer_idx": 3})
    assert a == b == '{"layer_idx":3,"node_idx":2}'


def test_canonicalize_no_whitespace():
    """No whitespace in the output — required for stable string comparison."""
    out = canonicalize_axes({"layer_idx": 3, "node_idx": 2})
    assert " " not in out


def test_canonicalize_coerces_int():
    """Integer-like values are stored as ints (not floats with `.0` suffix)."""
    out = canonicalize_axes({"layer_idx": 3})
    assert out == '{"layer_idx":3}'  # not `3.0`


def test_canonicalize_distinct_axis_sets_differ():
    """Different axis sets produce different canonical forms."""
    a = canonicalize_axes({"layer_idx": 3})
    b = canonicalize_axes({"layer_idx": 3, "node_idx": 0})
    assert a != b
