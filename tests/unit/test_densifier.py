"""Tests for the sparse → dense trajectory densifier."""
import pytest

from pred_fab_nocodb._densifier import densify
from pred_fab_nocodb.errors import ValidationError


def _e(step: int, value):
    """Build a sparse entry for the dimension ``layer_idx``."""
    return ({"layer_idx": step}, value)


def test_carry_forward_between_authored_steps():
    out = densify(
        {"speed": [_e(0, 0.005), _e(3, 0.006), _e(7, 0.008)]},
        dimension="layer_idx",
        n_steps=10,
    )
    assert out == {
        "speed": [0.005, 0.005, 0.005, 0.006, 0.006, 0.006, 0.006, 0.008, 0.008, 0.008],
    }


def test_backward_fill_when_first_entry_not_at_step_zero():
    """Steps before the first authored value get that value (no None)."""
    out = densify(
        {"speed": [_e(3, 0.006)]},
        dimension="layer_idx",
        n_steps=5,
    )
    assert out == {"speed": [0.006, 0.006, 0.006, 0.006, 0.006]}


def test_unsorted_input_is_sorted_by_step():
    """Entries delivered out of order should still produce the right dense list."""
    out = densify(
        {"speed": [_e(7, 0.008), _e(0, 0.005), _e(3, 0.006)]},
        dimension="layer_idx",
        n_steps=8,
    )
    assert out == {
        "speed": [0.005, 0.005, 0.005, 0.006, 0.006, 0.006, 0.006, 0.008],
    }


def test_multiple_codes_densified_independently():
    out = densify(
        {
            "speed": [_e(0, 0.005), _e(2, 0.007)],
            "calibration": [_e(1, 1.8)],
        },
        dimension="layer_idx",
        n_steps=4,
    )
    assert out == {
        "speed":       [0.005, 0.005, 0.007, 0.007],
        "calibration": [1.8,   1.8,   1.8,   1.8  ],
    }


def test_empty_entries_are_omitted():
    out = densify(
        {"speed": [_e(0, 0.005)], "calibration": []},
        dimension="layer_idx",
        n_steps=3,
    )
    assert "calibration" not in out
    assert out == {"speed": [0.005, 0.005, 0.005]}


def test_dense_lists_have_exactly_n_steps_length():
    out = densify(
        {"speed": [_e(0, 0.005), _e(7, 0.008)]},
        dimension="layer_idx",
        n_steps=12,
    )
    assert len(out["speed"]) == 12


def test_missing_dimension_in_entry_raises():
    with pytest.raises(ValidationError, match="missing dimension"):
        densify(
            {"speed": [({"node_idx": 0}, 0.005)]},
            dimension="layer_idx",
            n_steps=5,
        )


def test_step_index_at_or_above_n_steps_raises():
    with pytest.raises(ValidationError, match="n_steps=5"):
        densify(
            {"speed": [_e(5, 0.005)]},  # valid range is [0, 5)
            dimension="layer_idx",
            n_steps=5,
        )


def test_negative_step_index_raises():
    with pytest.raises(ValidationError):
        densify(
            {"speed": [_e(-1, 0.005)]},
            dimension="layer_idx",
            n_steps=5,
        )


def test_non_positive_n_steps_raises():
    with pytest.raises(ValidationError):
        densify({}, dimension="layer_idx", n_steps=0)
