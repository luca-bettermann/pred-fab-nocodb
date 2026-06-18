"""Tests for ConfigParamsClient (the relational `params` catalog) + coerce_value."""
import json

import pytest

from pred_fab_nocodb.config_params import (
    ConfigParamsClient,
    ConfigType,
    coerce_value,
)
from pred_fab_nocodb.errors import NotFoundError, ValidationError
from pred_fab_nocodb.schema import ConfigParamColumns


def _client(fake_http):
    return ConfigParamsClient(fake_http, base_id="b1", table_id="params")


# ===== upsert round-trip =====

def test_upsert_round_trips_a_param(fake_http):
    c = _client(fake_http)
    c.upsert(code="fab_speed", value=0.05, value_type=ConfigType.REAL,
             label="Fabrication speed", scope="knob", unit="m/s",
             description="extrusion speed")
    p = c.get_by_code("fab_speed")
    assert p.value == "0.05" and p.type is ConfigType.REAL
    assert p.label == "Fabrication speed" and p.scope == "knob" and p.unit == "m/s"
    assert p.description == "extrusion speed"
    assert p.coerced == pytest.approx(0.05)


def test_categorical_options_stored_as_json(fake_http):
    c = _client(fake_http)
    c.upsert(code="mode", value="clay", value_type=ConfigType.CATEGORICAL,
             options=["clay", "concrete"])
    row = next(r for r in fake_http.get_records("params") if r.get("code") == "mode")
    assert json.loads(row[ConfigParamColumns.OPTIONS]) == ["clay", "concrete"]
    assert c.get_by_code("mode").options == ["clay", "concrete"]


def test_read_returns_catalog_keyed_by_code(fake_http):
    c = _client(fake_http)
    c.upsert(code="a", value=1, value_type=ConfigType.INT)
    c.upsert(code="b", value=True, value_type=ConfigType.BOOL)
    catalog = c.read()
    assert set(catalog) == {"a", "b"}
    assert catalog["a"].coerced == 1 and catalog["b"].coerced is True


def test_get_by_code_missing_raises(fake_http):
    with pytest.raises(NotFoundError):
        _client(fake_http).get_by_code("nope")


def test_numeric_bounds_and_vector(fake_http):
    c = _client(fake_http)
    c.upsert(code="tool_offset", value=12.5, value_type=ConfigType.REAL,
             scope="safety", unit="mm", description="nozzle Z offset",
             min=0.0, max=50.0)
    c.upsert(code="home_joints", value=[0, -90, 90, 0, 90, 0], value_type=ConfigType.VECTOR)
    p = c.get_by_code("tool_offset")
    assert p.scope == "safety" and p.unit == "mm"
    assert p.min == pytest.approx(0.0) and p.max == pytest.approx(50.0)  # numeric Number column
    assert p.coerced_min == pytest.approx(0.0) and p.coerced_max == pytest.approx(50.0)
    assert c.get_by_code("home_joints").coerced == [0.0, -90.0, 90.0, 0.0, 90.0, 0.0]


def test_coerced_bounds_none_when_unset(fake_http):
    c = _client(fake_http)
    c.upsert(code="freeform", value="x", value_type=ConfigType.CATEGORICAL)
    p = c.get_by_code("freeform")
    assert p.min is None and p.max is None
    assert p.coerced_min is None and p.coerced_max is None


# ===== value-preserving upsert (the core contract) =====

def test_reupsert_preserves_runtime_value_refreshes_structure(fake_http):
    """Re-seeding refreshes structural metadata but never clobbers a runtime-edited value."""
    c = _client(fake_http)
    c.upsert(code="fab_speed", value=0.05, value_type=ConfigType.REAL, description="seed")

    # Simulate a runtime edit of the value in NocoDB.
    row = next(r for r in fake_http.get_records("params") if r.get("code") == "fab_speed")
    fake_http.records_update("params", {ConfigParamColumns.ID: row["Id"],
                                        ConfigParamColumns.VALUE: "0.09"})

    # Re-seed from the repo (same default value + updated structure).
    c.upsert(code="fab_speed", value=0.05, value_type=ConfigType.REAL, description="updated desc")

    p = c.get_by_code("fab_speed")
    assert p.value == "0.09"               # runtime value preserved, NOT reset to the seed default
    assert p.description == "updated desc"  # structure refreshed
    assert len(fake_http.get_records("params")) == 1   # updated in place, not duplicated


def test_first_upsert_writes_the_seed_default(fake_http):
    c = _client(fake_http)
    c.upsert(code="layer_h", value=2.0, value_type=ConfigType.REAL)
    assert c.get_by_code("layer_h").value == "2.0"   # seed default written on creation


# ===== coerce_value (the single raw→typed authority) =====

def test_coerce_value_by_type():
    assert coerce_value("0.05", ConfigType.REAL) == pytest.approx(0.05)
    assert coerce_value("5", ConfigType.INT) == 5
    assert coerce_value("clay", ConfigType.CATEGORICAL) == "clay"
    assert coerce_value("true", ConfigType.BOOL) is True
    assert coerce_value("0", ConfigType.BOOL) is False
    assert coerce_value("[1, 2, 3]", ConfigType.VECTOR) == [1.0, 2.0, 3.0]
    assert coerce_value('["a", "b"]', ConfigType.LIST) == ["a", "b"]
    assert coerce_value(None, ConfigType.REAL) is None


def test_coerce_value_strict_on_malformed():
    """A malformed value for its declared type raises — no silent degradation."""
    with pytest.raises(ValueError):
        coerce_value("not-a-number", ConfigType.REAL)
    with pytest.raises(ValidationError):
        coerce_value("maybe", ConfigType.BOOL)
