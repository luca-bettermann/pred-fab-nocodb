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
        # LTAR fields on set_exp_params — wired via /links/ endpoint.
        link_field_ids={"experiment": "fld_exp_link", "dim": "fld_dim_link"},
    )
    # Mirror NocoDB's behaviour: after link_records, the FK column on the row
    # gets populated with the linked id.
    fake_http.set_link_field("set_exp_params", "fld_exp_link", "experiment")
    fake_http.set_link_field("set_exp_params", "fld_dim_link", "dim")
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


def test_write_links_experiment_via_links_endpoint(fake_http):
    """Verify ValueClient.write hits NocoDB's /links/ endpoint for the experiment FK."""
    _dim, params = _make_clients(fake_http)
    params.write(
        exp_id=42, exp_code="ADVEI/exp_001",
        value_code="path_offset", value="2.5",
    )
    # Look for the link call on the experiment field
    links = [c for c in fake_http.calls if c[0] == "link_records"]
    exp_links = [c for c in links if c[2]["field"] == "fld_exp_link"]
    assert exp_links, "no link call to set the experiment FK"
    # Linked record id matches what we passed
    assert exp_links[0][3] == 42


def test_write_batch_links_experiment_and_dim(fake_http):
    """Each batched row gets its experiment link + dim link (when applicable).

    Fallback path: when `reverse_link_ids` isn't populated (the test fixture
    doesn't seed `colOptions`), `write_batch` issues per-row child-side
    calls — the original 2N behaviour.
    """
    _dim, params = _make_clients(fake_http)
    items = [
        ValueWriteItem(
            value_code="V_fab", value="0.005",
            domain="structural", axes={"layer_idx": 0},
        ),
        ValueWriteItem(
            value_code="V_fab", value="0.006",
            domain="structural", axes={"layer_idx": 1},
        ),
    ]
    params.write_batch(exp_id=42, exp_code="ADVEI/exp_001", items=items)
    links = [c for c in fake_http.calls if c[0] == "link_records"]
    exp_links = [c for c in links if c[2]["field"] == "fld_exp_link"]
    dim_links = [c for c in links if c[2]["field"] == "fld_dim_link"]
    # 2 experiment links (one per row), 2 dim links (one per row)
    assert len(exp_links) == 2
    assert len(dim_links) == 2
    # Both rows linked to the same experiment id
    assert all(c[3] == 42 for c in exp_links)
    # Dim ids are distinct (different layer_idx values)
    dim_target_ids = {c[3] for c in dim_links}
    assert len(dim_target_ids) == 2


def test_write_batch_collapses_links_via_reverse_side(fake_http):
    """When the reverse-link map is resolved (production path), `write_batch`
    issues ONE bulk parent-side `/links/` call per (parent, group) instead of
    2N child-side calls. Regression guard for the link-count optimisation."""
    dim = DimPositionsClient(fake_http, base_id="b1", table_id="dim_positions")
    fake_http.set_records("dim_positions", [])
    fake_http.set_records("set_exp_params", [])
    params = ValueClient(
        fake_http, base_id="b1", table_id="set_exp_params",
        fk_code_column="param", dim_client=dim,
        link_field_ids={"experiment": "fld_exp_link", "dim": "fld_dim_link"},
        reverse_link_ids={
            "experiment": ("experiments", "fld_exp_reverse"),
            "dim": ("dim_positions", "fld_dim_reverse"),
        },
    )
    fake_http.set_link_field("set_exp_params", "fld_exp_link", "experiment")
    fake_http.set_link_field("set_exp_params", "fld_dim_link", "dim")
    items = [
        ValueWriteItem(value_code="V_fab", value="0.005", domain="structural", axes={"layer_idx": 0}),
        ValueWriteItem(value_code="V_fab", value="0.006", domain="structural", axes={"layer_idx": 1}),
        ValueWriteItem(value_code="V_fab", value="0.007", domain="structural", axes={"layer_idx": 2}),
    ]
    params.write_batch(exp_id=42, exp_code="ADVEI/exp_001", items=items)

    links = [c for c in fake_http.calls if c[0] == "link_records"]
    # Old behaviour would have been 2N = 6 (one per row × 2 LTAR fields).
    # New: 1 parent-side call for experiment + 3 parent-side calls for dim
    # (one per unique dim_id) = 4.
    assert len(links) == 4

    exp_calls = [c for c in links if c[1] == "experiments"]
    assert len(exp_calls) == 1
    assert exp_calls[0][2]["field"] == "fld_exp_reverse"
    assert exp_calls[0][2]["record"] == 42  # parent record id
    # The single call carries every child row id at once.
    assert sorted(exp_calls[0][3]) == sorted([
        int(r["Id"]) for r in fake_http.get_records("set_exp_params")
    ])

    dim_calls = [c for c in links if c[1] == "dim_positions"]
    assert len(dim_calls) == 3  # one per unique dim_id
    for c in dim_calls:
        assert c[2]["field"] == "fld_dim_reverse"


def test_write_does_not_send_link_fields_in_records_create(fake_http):
    """LTAR fields must not appear in the records-create POST body."""
    _dim, params = _make_clients(fake_http)
    params.write(
        exp_id=42, exp_code="ADVEI/exp_001",
        value_code="V_fab", value="0.005",
        domain="structural", axes={"layer_idx": 0},
    )
    create_calls = [c for c in fake_http.calls if c[0] == "records_create"]
    assert create_calls, "expected at least one records_create"
    # The set_exp_params create body must not carry experiment / dim
    set_exp_params_creates = [c for c in create_calls if c[1] == "set_exp_params"]
    assert set_exp_params_creates
    body = set_exp_params_creates[0][3]
    assert ParamColumns.EXPERIMENT not in body
    assert ParamColumns.DIM not in body


# ─── Idempotent upsert ──────────────────────────────────────────────────


def test_write_is_idempotent_on_repeat(fake_http):
    """Same row code → no duplicate row, value gets updated in place."""
    _dim, params = _make_clients(fake_http)
    params.write(
        exp_id=1, exp_code="ADVEI/exp_001",
        value_code="path_offset", value="2.5",
    )
    params.write(
        exp_id=1, exp_code="ADVEI/exp_001",
        value_code="path_offset", value="3.0",
    )
    rows = fake_http.get_records("set_exp_params")
    assert len(rows) == 1
    assert rows[0][ParamColumns.VALUE] == "3.0"


def test_write_batch_is_idempotent_on_repeat(fake_http):
    """Repeating a write_batch with the same row codes updates rather than duplicates."""
    _dim, params = _make_clients(fake_http)
    items = [
        ValueWriteItem(value_code="V_fab", value="0.005",
                       domain="structural", axes={"layer_idx": 0}),
        ValueWriteItem(value_code="V_fab", value="0.006",
                       domain="structural", axes={"layer_idx": 1}),
    ]
    params.write_batch(exp_id=1, exp_code="ADVEI/exp_001", items=items)
    # Same items, different values
    items2 = [
        ValueWriteItem(value_code="V_fab", value="0.007",
                       domain="structural", axes={"layer_idx": 0}),
        ValueWriteItem(value_code="V_fab", value="0.008",
                       domain="structural", axes={"layer_idx": 1}),
    ]
    params.write_batch(exp_id=1, exp_code="ADVEI/exp_001", items=items2)
    rows = fake_http.get_records("set_exp_params")
    assert len(rows) == 2
    values = sorted(r[ParamColumns.VALUE] for r in rows)
    assert values == ["0.007", "0.008"]


def test_write_batch_constant_round_trips_in_n(fake_http):
    """write_batch issues a fixed number of value-table reads regardless of N —
    no per-row existence/refetch lookups (the old O(N) bottleneck)."""
    _dim, params = _make_clients(fake_http)

    def items(n):
        return [
            ValueWriteItem(value_code="print_speed", value=str(i),
                           domain="structural:nodes", axes={"layer_idx": i})
            for i in range(n)
        ]

    def value_reads():
        return sum(1 for c in fake_http.calls
                   if c[0] == "records_list" and c[1] == "set_exp_params")

    fake_http.calls.clear()
    params.write_batch(exp_id=1, exp_code="exp_a", items=items(4))
    small = value_reads()

    fake_http.calls.clear()
    params.write_batch(exp_id=2, exp_code="exp_b", items=items(16))
    large = value_reads()

    assert small == large    # constant in N
    assert small <= 2        # bulk pre-read + one id re-read; no per-row lookups


def test_write_batch_returns_correct_rows(fake_http):
    """Returned ValueRows are built in memory and carry the right fields."""
    _dim, params = _make_clients(fake_http)
    rows = params.write_batch(
        exp_id=7, exp_code="exp_x",
        items=[
            ValueWriteItem(value_code="print_speed", value="0.05",
                           domain="structural:nodes", axes={"layer_idx": 2}),
            ValueWriteItem(value_code="path_offset", value="1.5"),  # static, no dim
        ],
    )
    by_code = {r.code: r for r in rows}
    assert set(by_code) == {"exp_x/print_speed/structural:nodes.d1.0", "exp_x/path_offset"}
    assert all(r.experiment_id == 7 for r in rows)
    traj = by_code["exp_x/print_speed/structural:nodes.d1.0"]
    assert traj.dim_id is not None and traj.axes == {"layer_idx": 2} and traj.value == "0.05"
    static = by_code["exp_x/path_offset"]
    assert static.dim_id is None and static.axes == {} and static.value == "1.5"
    assert len(fake_http.get_records("set_exp_params")) == 2


def test_read_static_filters_to_null_dim(fake_http):
    _dim, params = _make_clients(fake_http)
    fake_http.set_records(
        "set_exp_params",
        [
            {ParamColumns.CODE: "exp_001/path_offset",
             ParamColumns.EXPERIMENT: {"Id": 1, "code": "exp_001"},
             "param": "path_offset", ParamColumns.VALUE: "2.5",
             ParamColumns.DIM: None},
            {ParamColumns.CODE: "exp_001/print_speed/d.d1.0",
             ParamColumns.EXPERIMENT: {"Id": 1, "code": "exp_001"},
             "param": "print_speed", ParamColumns.VALUE: "0.005",
             ParamColumns.DIM: {"Id": 1, "code": "d.d1.0"}},
            {ParamColumns.CODE: "exp_002/path_offset",
             ParamColumns.EXPERIMENT: {"Id": 2, "code": "exp_002"},
             "param": "path_offset", ParamColumns.VALUE: "9.9",
             ParamColumns.DIM: None},
        ],
    )
    static = params.read_static("exp_001")
    assert static == {"path_offset": 2.5}


def test_read_methods_filter_by_ltar_code_not_id(fake_http):
    """Regression: NocoDB v2 LTAR filters compare against the linked record's
    primary value (code), not the id. Confirm reads use the code path."""
    _dim, params = _make_clients(fake_http)
    fake_http.set_records(
        "set_exp_params",
        [
            {ParamColumns.CODE: "ADVEI_2026/reference/000/pathOffset",
             ParamColumns.EXPERIMENT: {"Id": 71, "code": "ADVEI_2026/reference/000"},
             "param": "pathOffset", ParamColumns.VALUE: "1.5",
             ParamColumns.DIM: None},
        ],
    )
    # Filtering by code returns the row.
    assert params.read_static("ADVEI_2026/reference/000") == {"pathOffset": 1.5}
    # Filtering by stringified id does NOT — would silently return empty if
    # someone reverts the fix.
    assert params.read_static("71") == {}
