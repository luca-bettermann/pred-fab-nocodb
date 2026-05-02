"""Tests for ValueClient — covers params/features/attributes shape."""
from pred_fab_nocodb._values import ValueClient, ValueWriteItem
from pred_fab_nocodb.dim_positions import DimPositionsClient
from pred_fab_nocodb.schema import ParamColumns


def _make_clients(fake_http):
    dim = DimPositionsClient(fake_http, base_id="b1", table_id="dim_positions")
    fake_http.set_records("dim_positions", [])
    fake_http.set_records("set_exp_params", [])
    params = ValueClient(
        fake_http,
        base_id="b1",
        table_id="set_exp_params",
        fk_code_column="param",
        dim_client=dim,
    )
    return dim, params


def test_write_static_no_dim(fake_http):
    _dim, params = _make_clients(fake_http)
    row = params.write(
        exp_id=1, exp_code="ADVEI_2026_001",
        value_code="path_offset", value="2.5",
    )
    assert row.fk_code == "path_offset"
    assert row.dim_id is None
    assert row.code == "ADVEI_2026_001/path_offset"


def test_write_trajectory_creates_dim(fake_http):
    _dim, params = _make_clients(fake_http)
    row = params.write(
        exp_id=1, exp_code="ADVEI_2026_001",
        value_code="print_speed", value="0.005",
        domain="structural:nodes", axes={"layer_idx": 3},
    )
    assert row.dim_id is not None
    assert row.code == "ADVEI_2026_001/print_speed/structural:nodes.d1.0"
    # dim_position was upserted
    assert len(fake_http.get_records("dim_positions")) == 1


def test_write_batch_reuses_dim(fake_http):
    _dim, params = _make_clients(fake_http)
    items = [
        ValueWriteItem(
            value_code="print_speed", value="0.004",
            domain="structural:nodes", axes={"layer_idx": 0},
        ),
        ValueWriteItem(
            value_code="slowdown_factor", value="0.5",
            domain="structural:nodes", axes={"layer_idx": 0},   # same axes!
        ),
    ]
    params.write_batch(exp_id=1, exp_code="exp_001", items=items)
    # Same dim_position used for both
    assert len(fake_http.get_records("dim_positions")) == 1
    assert len(fake_http.get_records("set_exp_params")) == 2


def test_read_static_filters_to_null_dim(fake_http):
    _dim, params = _make_clients(fake_http)
    fake_http.set_records(
        "set_exp_params",
        [
            {ParamColumns.CODE: "exp_001/path_offset", ParamColumns.EXPERIMENT: 1,
             "param": "path_offset", ParamColumns.VALUE: "2.5",
             ParamColumns.DIM: None},
            {ParamColumns.CODE: "exp_001/print_speed/d.d1.0", ParamColumns.EXPERIMENT: 1,
             "param": "print_speed", ParamColumns.VALUE: "0.005",
             ParamColumns.DIM: 1},
        ],
    )
    static = params.read_static(1)
    assert static == {"path_offset": "2.5"}
