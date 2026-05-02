"""Tests for StudiesClient against the fake HTTP backend."""
import pytest

from pred_fab_nocodb.errors import NotFoundError
from pred_fab_nocodb.schema import StudyColumns
from pred_fab_nocodb.studies import StudiesClient


def test_get_by_code_returns_study(fake_http):
    fake_http.set_records(
        "studies",
        [{StudyColumns.CODE: "ADVEI_2026", StudyColumns.DESCRIPTION: "test"}],
    )
    client = StudiesClient(fake_http, base_id="b1", table_id="studies")
    study = client.get_by_code("ADVEI_2026")
    assert study.code == "ADVEI_2026"
    assert study.description == "test"


def test_get_by_code_raises_when_absent(fake_http):
    fake_http.set_records("studies", [])
    client = StudiesClient(fake_http, base_id="b1", table_id="studies")
    with pytest.raises(NotFoundError):
        client.get_by_code("nonexistent")


def test_create_writes_row(fake_http):
    client = StudiesClient(fake_http, base_id="b1", table_id="studies")
    client.create(code="ADVEI_2026", description="Curved-wall study")
    rows = fake_http.get_records("studies")
    assert len(rows) == 1
    assert rows[0][StudyColumns.CODE] == "ADVEI_2026"
    assert rows[0][StudyColumns.DESCRIPTION] == "Curved-wall study"


def test_list_all_returns_all_rows(fake_http):
    fake_http.set_records(
        "studies",
        [
            {StudyColumns.CODE: "S1"},
            {StudyColumns.CODE: "S2"},
        ],
    )
    client = StudiesClient(fake_http, base_id="b1", table_id="studies")
    studies = client.list_all()
    assert {s.code for s in studies} == {"S1", "S2"}


def test_push_schema_serialises_to_json_string(fake_http):
    fake_http.set_records("studies", [{StudyColumns.CODE: "S1"}])
    client = StudiesClient(fake_http, base_id="b1", table_id="studies")
    schema = {"params": [{"code": "speed", "low": 0.004, "high": 0.008}]}
    study_id = fake_http.get_records("studies")[0]["Id"]

    client.push_schema(study_id, schema)

    stored = fake_http.get_records("studies")[0][StudyColumns.SCHEMA]
    import json as _json
    assert _json.loads(stored) == schema


def test_pull_schema_round_trips(fake_http):
    fake_http.set_records("studies", [{StudyColumns.CODE: "S1"}])
    client = StudiesClient(fake_http, base_id="b1", table_id="studies")
    schema = {"a": 1, "b": [1, 2, 3]}
    study_id = fake_http.get_records("studies")[0]["Id"]

    client.push_schema(study_id, schema)
    assert client.pull_schema(study_id) == schema


def test_pull_schema_returns_none_when_empty(fake_http):
    fake_http.set_records("studies", [{StudyColumns.CODE: "S1"}])
    client = StudiesClient(fake_http, base_id="b1", table_id="studies")
    study_id = fake_http.get_records("studies")[0]["Id"]
    assert client.pull_schema(study_id) is None
