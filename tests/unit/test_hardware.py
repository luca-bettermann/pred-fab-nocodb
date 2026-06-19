"""Tests for HardwareClient (device identity)."""
import pytest

from pred_fab_nocodb.errors import NotFoundError
from pred_fab_nocodb.hardware import HardwareClient
from pred_fab_nocodb.schema import HardwareType


def _client(fake_http):
    return HardwareClient(fake_http, base_id="b1", table_id="hardware")


def test_upsert_round_trips_a_device(fake_http):
    c = _client(fake_http)
    c.upsert(name="UR10e", device_type=HardwareType.ROBOT, kind="UR10e")
    h = c.get_by_name("UR10e")
    assert h.type is HardwareType.ROBOT and h.kind == "UR10e"


def test_upsert_is_idempotent(fake_http):
    c = _client(fake_http)
    c.upsert(name="Gocator", device_type=HardwareType.SENSOR, kind="Gocator2530")
    c.upsert(name="Gocator", device_type=HardwareType.SENSOR, kind="Gocator2530")
    assert len(fake_http.get_records("hardware")) == 1
    assert set(c.read()) == {"Gocator"}


def test_get_by_name_missing_raises(fake_http):
    with pytest.raises(NotFoundError):
        _client(fake_http).get_by_name("nope")
