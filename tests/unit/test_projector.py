"""Tests for the trajectory dimension projector."""
import pytest

from pred_fab_nocodb._projector import project_to_dimension
from pred_fab_nocodb.errors import ValidationError


def _e(step: int, value, dim: str = "layer_idx"):
    """Build a sparse entry for a given dimension."""
    return ({dim: step}, value)


def test_project_returns_step_keyed_dict():
    out = project_to_dimension(
        {"speed": [_e(0, 0.005), _e(3, 0.006), _e(7, 0.008)]},
        dimension="layer_idx",
    )
    assert out == {"speed": {0: 0.005, 3: 0.006, 7: 0.008}}


def test_unsorted_input_yields_dict_unchanged():
    """Order-independence: dicts are unordered; the projector doesn't care."""
    out = project_to_dimension(
        {"speed": [_e(7, 0.008), _e(0, 0.005), _e(3, 0.006)]},
        dimension="layer_idx",
    )
    assert out == {"speed": {0: 0.005, 3: 0.006, 7: 0.008}}


def test_multiple_codes_projected_independently():
    out = project_to_dimension(
        {
            "speed": [_e(0, 0.005), _e(2, 0.007)],
            "calibration": [_e(1, 1.8)],
        },
        dimension="layer_idx",
    )
    assert out == {
        "speed": {0: 0.005, 2: 0.007},
        "calibration": {1: 1.8},
    }


def test_empty_entries_are_omitted():
    out = project_to_dimension(
        {"speed": [_e(0, 0.005)], "calibration": []},
        dimension="layer_idx",
    )
    assert "calibration" not in out
    assert out == {"speed": {0: 0.005}}


def test_repeated_step_keeps_last_entry():
    """If two entries land on the same step, dict semantics: last wins.

    Real NocoDB writes shouldn't produce this (uniqueness on
    (experiment, param, dim)), but the projector is defensive."""
    out = project_to_dimension(
        {"speed": [_e(3, 0.005), _e(3, 0.009)]},
        dimension="layer_idx",
    )
    assert out == {"speed": {3: 0.009}}


def test_missing_dimension_in_entry_raises():
    with pytest.raises(ValidationError, match="missing dimension"):
        project_to_dimension(
            {"speed": [({"node_idx": 0}, 0.005)]},
            dimension="layer_idx",
        )


def test_negative_step_index_raises():
    with pytest.raises(ValidationError, match="negative step"):
        project_to_dimension(
            {"speed": [_e(-1, 0.005)]},
            dimension="layer_idx",
        )


def test_alternative_dimension_names():
    """Projection works for any axis name, not just layer_idx."""
    out = project_to_dimension(
        {"capture_offset": [_e(0, 0.01, dim="node_idx"), _e(2, 0.02, dim="node_idx")]},
        dimension="node_idx",
    )
    assert out == {"capture_offset": {0: 0.01, 2: 0.02}}
