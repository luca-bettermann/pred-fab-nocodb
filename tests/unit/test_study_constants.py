"""Tests for StudyConstantsClient — read, write, write_batch, delete."""
import pytest

from pred_fab_nocodb.errors import NotFoundError
from pred_fab_nocodb.schema import StudyConstantColumns
from pred_fab_nocodb.study_constants import StudyConstantsClient


def _make_client(fake_http):
    fake_http.set_records("study_constants", [])
    return StudyConstantsClient(
        fake_http, base_id="b1", table_id="study_constants",
        link_field_ids={"study": "fld_study_link"},
    )


def test_write_inserts_when_absent(fake_http):
    client = _make_client(fake_http)
    client.write(study_id=42, study_code="ADVEI", param_code="W_filament", value=0.007)
    rows = fake_http.get_records("study_constants")
    assert len(rows) == 1
    assert rows[0][StudyConstantColumns.PARAM] == "W_filament"
    assert rows[0][StudyConstantColumns.VALUE] == 0.007


def test_write_updates_when_present(fake_http):
    client = _make_client(fake_http)
    fake_http.set_link_field("study_constants", "fld_study_link", "study")
    fake_http.set_records(
        "study_constants",
        [{StudyConstantColumns.CODE: "ADVEI/W_filament",
          StudyConstantColumns.PARAM: "W_filament",
          StudyConstantColumns.VALUE: 0.005,
          "study": 42}],
    )
    client.write(study_id=42, study_code="ADVEI", param_code="W_filament", value=0.007)
    rows = fake_http.get_records("study_constants")
    assert len(rows) == 1
    assert rows[0][StudyConstantColumns.VALUE] == 0.007


def test_write_batch_upserts_each_key(fake_http):
    client = _make_client(fake_http)
    client.write_batch(
        study_id=42, study_code="ADVEI",
        constants={"W_filament": 0.007, "component_height_mm": 25.0},
    )
    rows = fake_http.get_records("study_constants")
    assert len(rows) == 2
    by_param = {r[StudyConstantColumns.PARAM]: r[StudyConstantColumns.VALUE] for r in rows}
    assert by_param == {"W_filament": 0.007, "component_height_mm": 25.0}


def test_write_batch_leaves_other_constants_alone(fake_http):
    """write_batch only upserts the keys it's handed; other rows untouched."""
    client = _make_client(fake_http)
    fake_http.set_link_field("study_constants", "fld_study_link", "study")
    fake_http.set_records(
        "study_constants",
        [{StudyConstantColumns.CODE: "ADVEI/water_ratio",
          StudyConstantColumns.PARAM: "water_ratio",
          StudyConstantColumns.VALUE: 0.25,
          "study": 42}],
    )
    client.write_batch(
        study_id=42, study_code="ADVEI",
        constants={"W_filament": 0.007},
    )
    rows = fake_http.get_records("study_constants")
    by_param = {r[StudyConstantColumns.PARAM]: r[StudyConstantColumns.VALUE] for r in rows}
    assert by_param == {"water_ratio": 0.25, "W_filament": 0.007}


def test_write_batch_empty_constants_is_noop(fake_http):
    client = _make_client(fake_http)
    client.write_batch(study_id=42, study_code="ADVEI", constants={})
    assert fake_http.get_records("study_constants") == []


def test_read_returns_constants_for_study(fake_http):
    client = _make_client(fake_http)
    fake_http.set_records(
        "study_constants",
        [
            {StudyConstantColumns.STUDY: 42,
             StudyConstantColumns.PARAM: "W_filament",
             StudyConstantColumns.VALUE: 0.007},
            {StudyConstantColumns.STUDY: 99,
             StudyConstantColumns.PARAM: "elsewhere",
             StudyConstantColumns.VALUE: 1.0},
        ],
    )
    result = client.read(study_id=42)
    assert result == {"W_filament": 0.007}


def test_delete_removes_existing(fake_http):
    client = _make_client(fake_http)
    fake_http.set_records(
        "study_constants",
        [{StudyConstantColumns.STUDY: 42,
          StudyConstantColumns.PARAM: "W_filament",
          StudyConstantColumns.VALUE: 0.007}],
    )
    client.delete(study_id=42, param_code="W_filament")
    assert fake_http.get_records("study_constants") == []


def test_delete_raises_when_absent(fake_http):
    client = _make_client(fake_http)
    with pytest.raises(NotFoundError):
        client.delete(study_id=42, param_code="missing")
