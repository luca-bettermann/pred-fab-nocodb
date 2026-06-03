"""Tests for ExperimentsClient against the fake HTTP backend."""
from pred_fab_nocodb.experiments import ExperimentsClient
from pred_fab_nocodb.schema import ExperimentColumns


def _client(fake_http):
    return ExperimentsClient(fake_http, base_id="b1", table_id="experiments")


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
