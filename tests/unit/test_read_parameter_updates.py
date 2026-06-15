"""Trajectory read-back: ``ValueClient.read_parameter_updates`` round-trip.

The only existing caller of ``read_parameter_updates`` stubs it out
(``test_workflows_load_for_fabrication``); nothing drives it through the fake
HTTP backend. This seeds a realistic single-axis trajectory and asserts the
read projects it back to sorted, coerced, dim-collapsed
``ParameterUpdateEvent``s — and that the documented coercion divergence with
``read_trajectory`` holds.
"""
from pred_fab_nocodb._values import ValueClient
from pred_fab_nocodb.dim_positions import DimPositionsClient
from pred_fab_nocodb.errors import ValidationError
from pred_fab_nocodb.schema import DimPositionColumns, ParamColumns

import pytest


def _make_clients(fake_http):
    dim = DimPositionsClient(fake_http, base_id="b1", table_id="dim_positions")
    params = ValueClient(
        fake_http,
        base_id="b1",
        table_id="set_exp_params",
        fk_code_column="param",
        dim_client=dim,
        link_field_ids={"experiment": "fld_exp_link", "dim": "fld_dim_link"},
    )
    fake_http.set_link_field("set_exp_params", "fld_exp_link", "experiment")
    fake_http.set_link_field("set_exp_params", "fld_dim_link", "dim")
    return dim, params


def _dim_row(id_, step):
    return {
        DimPositionColumns.ID: id_,
        DimPositionColumns.CODE: f"d.layer_idx.{step}",
        DimPositionColumns.DOMAIN: "structural",
        DimPositionColumns.DEPTH: 1,
        DimPositionColumns.AXES: f'{{"layer_idx":{step}}}',
    }


def _param_row(code, exp_code, exp_id, param, value, dim_id=None, dim_code=None):
    return {
        ParamColumns.CODE: code,
        ParamColumns.EXPERIMENT: {"Id": exp_id, "code": exp_code},
        "param": param,
        ParamColumns.VALUE: value,
        ParamColumns.DIM: {"Id": dim_id, "code": dim_code} if dim_id is not None else None,
    }


def _seed_trajectory(fake_http):
    """A 3-layer trajectory for exp_traj + noise (static row, other experiment)."""
    fake_http.set_records("dim_positions", [_dim_row(101, 0), _dim_row(102, 1), _dim_row(103, 2)])
    fake_http.set_records(
        "set_exp_params",
        [
            # Seeded out of step order to exercise the sort.
            _param_row("exp_traj/print_speed/l2", "exp_traj", 1, "print_speed", "0.007", 103, "d.layer_idx.2"),
            _param_row("exp_traj/print_speed/l0", "exp_traj", 1, "print_speed", "0.005", 101, "d.layer_idx.0"),
            # Same dim (layer 0) as print_speed → collapses into one event.
            _param_row("exp_traj/path_offset/l0", "exp_traj", 1, "path_offset", "2", 101, "d.layer_idx.0"),
            _param_row("exp_traj/print_speed/l1", "exp_traj", 1, "print_speed", "0.006", 102, "d.layer_idx.1"),
            # Static (dim unset) — excluded by the notblank filter.
            _param_row("exp_traj/path_offset", "exp_traj", 1, "path_offset", "1.5"),
            # Different experiment — excluded by the experiment-code filter.
            _param_row("exp_other/print_speed/l0", "exp_other", 9, "print_speed", "9.9", 101, "d.layer_idx.0"),
        ],
    )


def test_read_parameter_updates_roundtrip(fake_http):
    _dim, params = _make_clients(fake_http)
    _seed_trajectory(fake_http)

    events = params.read_parameter_updates("exp_traj")

    # One event per dim, sorted by (iterator_code, step_index); static + other-exp excluded.
    assert [e.step_index for e in events] == [0, 1, 2]
    assert all(e.iterator_code == "layer_idx" for e in events)

    # Rows sharing dim (layer 0) collapse into a single event's updates dict.
    assert events[0].updates == {"print_speed": 0.005, "path_offset": 2}
    assert events[1].updates == {"print_speed": 0.006}
    assert events[2].updates == {"print_speed": 0.007}


def test_read_parameter_updates_coerces_numeric_strings(fake_http):
    """Stored value strings become int/float; non-numeric stays a string."""
    _dim, params = _make_clients(fake_http)
    fake_http.set_records("dim_positions", [_dim_row(101, 0)])
    fake_http.set_records(
        "set_exp_params",
        [
            _param_row("exp/a/l0", "exp", 1, "n_passes", "5", 101, "d.layer_idx.0"),
            _param_row("exp/b/l0", "exp", 1, "offset", "-3", 101, "d.layer_idx.0"),
            _param_row("exp/c/l0", "exp", 1, "speed", "0.006", 101, "d.layer_idx.0"),
            _param_row("exp/d/l0", "exp", 1, "mode", "fast", 101, "d.layer_idx.0"),
        ],
    )

    updates = params.read_parameter_updates("exp")[0].updates
    assert updates["n_passes"] == 5 and isinstance(updates["n_passes"], int)
    assert updates["offset"] == -3 and isinstance(updates["offset"], int)
    assert updates["speed"] == pytest.approx(0.006) and isinstance(updates["speed"], float)
    assert updates["mode"] == "fast" and isinstance(updates["mode"], str)


def test_read_parameter_updates_rejects_multi_axis(fake_http):
    """A multi-axis dim_position cannot project onto a single-axis event."""
    _dim, params = _make_clients(fake_http)
    fake_http.set_records(
        "dim_positions",
        [{
            DimPositionColumns.ID: 201,
            DimPositionColumns.CODE: "d.multi",
            DimPositionColumns.DOMAIN: "structural",
            DimPositionColumns.DEPTH: 2,
            DimPositionColumns.AXES: '{"layer_idx":0,"node_idx":1}',
        }],
    )
    fake_http.set_records(
        "set_exp_params",
        [_param_row("exp/x", "exp", 1, "print_speed", "0.005", 201, "d.multi")],
    )

    with pytest.raises(ValidationError):
        params.read_parameter_updates("exp")


def test_read_trajectory_does_not_coerce_unlike_parameter_updates(fake_http):
    """Documents the audit-noted divergence: read_trajectory returns the raw
    stored string; read_parameter_updates coerces it."""
    _dim, params = _make_clients(fake_http)
    fake_http.set_records("dim_positions", [_dim_row(101, 0)])
    fake_http.set_records(
        "set_exp_params",
        [_param_row("exp/s/l0", "exp", 1, "print_speed", "0.005", 101, "d.layer_idx.0")],
    )

    raw_axes, raw_value = params.read_trajectory("exp")["print_speed"][0]
    assert raw_value == "0.005"  # uncoerced
    assert raw_axes == {"layer_idx": 0}

    coerced = params.read_parameter_updates("exp")[0].updates["print_speed"]
    assert coerced == pytest.approx(0.005) and isinstance(coerced, float)
