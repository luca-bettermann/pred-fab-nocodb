"""Tests for DimPositionsClient — covers the get_or_create + counter logic."""
from pred_fab_nocodb.dim_positions import DimPositionsClient
from pred_fab_nocodb.schema import DimPositionColumns


def test_get_or_create_creates_when_absent(fake_http):
    fake_http.set_records("dim_positions", [])
    client = DimPositionsClient(fake_http, base_id="b1", table_id="dim_positions")
    pos = client.get_or_create(domain="structural:nodes", axes={"layer_idx": 3, "node_idx": 2})
    assert pos.domain == "structural:nodes"
    assert pos.depth == 2
    assert pos.axes == {"layer_idx": 3, "node_idx": 2}
    assert pos.code == "structural:nodes.d2.0"   # first at this (domain, depth)


def test_get_or_create_is_idempotent(fake_http):
    fake_http.set_records("dim_positions", [])
    client = DimPositionsClient(fake_http, base_id="b1", table_id="dim_positions")
    a = client.get_or_create(domain="structural:nodes", axes={"layer_idx": 3, "node_idx": 2})
    b = client.get_or_create(domain="structural:nodes", axes={"layer_idx": 3, "node_idx": 2})
    assert a.id == b.id
    # Only one row should exist
    assert len(fake_http.get_records("dim_positions")) == 1


def test_counter_per_domain_depth(fake_http):
    fake_http.set_records("dim_positions", [])
    client = DimPositionsClient(fake_http, base_id="b1", table_id="dim_positions")
    p0 = client.get_or_create(domain="structural:nodes", axes={"layer_idx": 0})
    p1 = client.get_or_create(domain="structural:nodes", axes={"layer_idx": 1})
    p2 = client.get_or_create(domain="structural:nodes", axes={"layer_idx": 0, "node_idx": 0})
    # depth-1 counter starts at 0; depth-2 counter independently starts at 0
    assert p0.code == "structural:nodes.d1.0"
    assert p1.code == "structural:nodes.d1.1"
    assert p2.code == "structural:nodes.d2.0"


def test_axes_canonicalised_for_uniqueness(fake_http):
    """Insertion order of axis keys doesn't create duplicate rows."""
    fake_http.set_records("dim_positions", [])
    client = DimPositionsClient(fake_http, base_id="b1", table_id="dim_positions")
    a = client.get_or_create(domain="d", axes={"layer_idx": 3, "node_idx": 2})
    b = client.get_or_create(domain="d", axes={"node_idx": 2, "layer_idx": 3})
    assert a.id == b.id
    assert len(fake_http.get_records("dim_positions")) == 1


def test_find_returns_none_when_absent(fake_http):
    fake_http.set_records("dim_positions", [])
    client = DimPositionsClient(fake_http, base_id="b1", table_id="dim_positions")
    assert client.find(domain="d", axes={"layer_idx": 0}) is None


def test_link_ancestors_writes_contained_in(fake_http):
    """A multi-axis dim links to its prefix ancestor via the contained_in self-link."""
    fake_http.set_records("dim_positions", [])
    client = DimPositionsClient(
        fake_http, base_id="b1", table_id="dim_positions",
        link_field_ids={DimPositionColumns.CONTAINED_IN: "fld_contained_in"},
    )
    parent = client.get_or_create(domain="d", axes={"layer_idx": 0})
    child = client.get_or_create(domain="d", axes={"layer_idx": 0, "node_idx": 0})
    assert any(
        fid == "fld_contained_in" and rid == child.id and parent.id in linked
        for (_tid, fid, rid, linked) in fake_http.link_calls
    )


def test_link_ancestors_skipped_without_link_field(fake_http):
    """A client without the self-link field skips linking instead of erroring."""
    fake_http.set_records("dim_positions", [])
    client = DimPositionsClient(fake_http, base_id="b1", table_id="dim_positions")
    client.get_or_create(domain="d", axes={"layer_idx": 0})
    client.get_or_create(domain="d", axes={"layer_idx": 0, "node_idx": 0})
    assert fake_http.link_calls == []


def test_list_by_domain_with_depth_filter(fake_http):
    fake_http.set_records(
        "dim_positions",
        [
            {DimPositionColumns.CODE: "d1.d1.0", DimPositionColumns.DOMAIN: "d1",
             DimPositionColumns.DEPTH: 1, DimPositionColumns.AXES: '{"layer_idx":0}'},
            {DimPositionColumns.CODE: "d1.d2.0", DimPositionColumns.DOMAIN: "d1",
             DimPositionColumns.DEPTH: 2, DimPositionColumns.AXES: '{"layer_idx":0,"node_idx":0}'},
        ],
    )
    client = DimPositionsClient(fake_http, base_id="b1", table_id="dim_positions")
    depth1 = client.list_by_domain(domain="d1", depth=1)
    assert len(depth1) == 1
    assert depth1[0].depth == 1
