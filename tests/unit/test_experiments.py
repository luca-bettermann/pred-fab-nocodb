"""Tests for ExperimentsClient against the fake HTTP backend."""
import json

from pred_fab_nocodb.experiments import ExperimentsClient
from pred_fab_nocodb.schema import ExperimentColumns, Status


def _client(fake_http):
    return ExperimentsClient(fake_http, base_id="b1", table_id="experiments")


def _client_linked(fake_http):
    """Client wired for the `studies` link (upsert re-asserts it)."""
    fake_http.set_link_field("experiments", "fld_studies", ExperimentColumns.STUDIES)
    return ExperimentsClient(
        fake_http, base_id="b1", table_id="experiments",
        link_field_ids={ExperimentColumns.STUDIES: "fld_studies"},
    )


def test_list_codes_returns_all_codes(fake_http):
    fake_http.set_records(
        "experiments",
        [
            {ExperimentColumns.CODE: "reference/004"},
            {ExperimentColumns.CODE: "reference/005"},
            {ExperimentColumns.CODE: "train/001"},
        ],
    )
    assert set(_client(fake_http).list_codes()) == {
        "reference/004",
        "reference/005",
        "train/001",
    }


def test_list_codes_filters_by_dataset_namespace(fake_http):
    fake_http.set_records(
        "experiments",
        [
            {ExperimentColumns.CODE: "reference/004"},
            {ExperimentColumns.CODE: "reference/005"},
            {ExperimentColumns.CODE: "train/001"},
        ],
    )
    assert set(_client(fake_http).list_codes(dataset="reference")) == {
        "reference/004",
        "reference/005",
    }


def test_list_codes_empty_table(fake_http):
    fake_http.set_records("experiments", [])
    assert _client(fake_http).list_codes() == []


# ===== generative provenance (design + provenance columns) =====

def test_read_parses_design_and_provenance_json(fake_http):
    fake_http.set_records(
        "experiments",
        [
            {
                ExperimentColumns.CODE: "e1",
                ExperimentColumns.DESIGN: "exploration",
                ExperimentColumns.PROVENANCE: '{"design": "exploration", "kappa": 0.4}',
            },
            {ExperimentColumns.CODE: "e2"},  # no design / provenance
        ],
    )
    client = _client(fake_http)
    e1 = client.get_by_code("e1")
    assert e1.design == "exploration"
    assert e1.provenance == {"design": "exploration", "kappa": 0.4}
    e2 = client.get_by_code("e2")
    assert e2.design is None
    assert e2.provenance is None


def test_upsert_writes_design_and_provenance_json(fake_http):
    client = _client_linked(fake_http)
    client.upsert(study_id=1, code="sobol/001", design="sobol", provenance={"seed": 1})
    row = next(r for r in fake_http.get_records("experiments") if r.get("code") == "sobol/001")
    assert row[ExperimentColumns.DESIGN] == "sobol"
    assert json.loads(row[ExperimentColumns.PROVENANCE]) == {"seed": 1}  # JSON in LongText


def test_upsert_round_trips_provenance(fake_http):
    client = _client_linked(fake_http)
    snap = {"design": "sobol", "seed": 7, "kappa": None, "param_bounds": {"p": [0, 10]}}
    client.upsert(study_id=1, code="sobol/002", design="sobol", provenance=snap)
    exp = client.get_by_code("sobol/002")
    assert exp.design == "sobol"
    assert exp.provenance == snap
