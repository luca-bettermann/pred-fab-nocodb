"""Tests for ExperimentSetsClient against the fake HTTP backend."""
import json

import pytest

from pred_fab_nocodb.errors import NotFoundError
from pred_fab_nocodb.experiment_sets import ExperimentSetsClient
from pred_fab_nocodb.schema import ExperimentSetColumns


def _client(fake_http):
    return ExperimentSetsClient(fake_http, base_id="b1", table_id="experiment_sets")


def test_upsert_round_trips_a_group(fake_http):
    c = _client(fake_http)
    c.upsert(code="E1", strategy="exploration", ordered=True, parent="D1", members=["e1", "e2"])
    es = c.get_by_code("E1")
    assert es.strategy == "exploration" and es.ordered is True
    assert es.parent == "D1" and es.members == ["e1", "e2"]


def test_members_stored_as_json(fake_http):
    c = _client(fake_http)
    c.upsert(code="D1", strategy="discovery", members=["a", "b"])
    row = next(r for r in fake_http.get_records("experiment_sets") if r.get("code") == "D1")
    assert json.loads(row[ExperimentSetColumns.MEMBERS]) == ["a", "b"]


def test_batch_set_has_no_parent_and_defaults_unordered(fake_http):
    c = _client(fake_http)
    c.upsert(code="D1", strategy="discovery", members=["a"])
    es = c.get_by_code("D1")
    assert es.ordered is False and es.parent is None


def test_list_all_returns_every_group(fake_http):
    c = _client(fake_http)
    c.upsert(code="D1", strategy="discovery", members=["a"])
    c.upsert(code="E1", strategy="exploration", ordered=True, parent="D1", members=["e1"])
    assert {es.code for es in c.list_all()} == {"D1", "E1"}


def test_upsert_updates_in_place(fake_http):
    c = _client(fake_http)
    c.upsert(code="D1", strategy="discovery", members=["a"])
    c.upsert(code="D1", strategy="discovery", members=["a", "b", "c"])
    assert c.get_by_code("D1").members == ["a", "b", "c"]
    assert len(fake_http.get_records("experiment_sets")) == 1     # updated, not duplicated


def test_get_by_code_missing_raises(fake_http):
    with pytest.raises(NotFoundError):
        _client(fake_http).get_by_code("nope")
