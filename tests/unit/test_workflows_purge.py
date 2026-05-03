"""Tests for WorkflowsClient.purge_dataset."""
from dataclasses import dataclass, field
from typing import Any

from pred_fab_nocodb.workflows import WorkflowsClient
from pred_fab_nocodb.schema import (
    AttributeColumns,
    DatasetColumns,
    ExperimentColumns,
    FeatureColumns,
    ParamColumns,
    Status,
)


# ─── Stub clients (lighter than the full FakeNocoDBHttp setup) ──────────


@dataclass
class _FakeDataset:
    id: int
    code: str


@dataclass
class _FakeExperiment:
    id: int
    code: str
    status: Status = Status.DRAFT


@dataclass
class _StubDatasets:
    by_code: dict[str, _FakeDataset] = field(default_factory=dict)
    table_id: str = "datasets"

    def get_by_code(self, code: str) -> _FakeDataset:
        from pred_fab_nocodb.errors import NotFoundError
        if code not in self.by_code:
            raise NotFoundError(code)
        return self.by_code[code]

    @property
    def _table_id(self) -> str:  # client.py introspects this
        return self.table_id


@dataclass
class _StubExperiments:
    by_dataset: dict[int, list[_FakeExperiment]] = field(default_factory=dict)
    table_id: str = "experiments"

    def list_by_dataset(self, dataset_id: int) -> list[_FakeExperiment]:
        return list(self.by_dataset.get(dataset_id, []))

    @property
    def _table_id(self) -> str:
        return self.table_id


@dataclass
class _StubValuesByExp:
    """Minimal value-client surface used by purge_dataset (just _table_id)."""
    table_id: str

    @property
    def _table_id(self) -> str:
        return self.table_id


@dataclass
class _StubHttp:
    """Captures records_list / records_delete calls; serves seeded value rows."""

    rows_by_table_and_exp: dict[tuple[str, int], list[dict[str, Any]]] = field(default_factory=dict)
    deletes: list[tuple[str, list[int]]] = field(default_factory=list)

    def records_list(self, table_id: str, *, where: str = "", **kwargs: Any) -> list[dict[str, Any]]:
        # Parse `(experiment,eq,N)` from where clause to match behaviour of real http
        for (tid, exp_id), rows in self.rows_by_table_and_exp.items():
            if tid == table_id and where == f"(experiment,eq,{exp_id})":
                return rows
        return []

    def records_delete(self, table_id: str, body: Any) -> None:
        if isinstance(body, list):
            ids = [int(b.get("Id", -1)) for b in body]
        else:
            ids = [int(body.get("Id", -1))]
        self.deletes.append((table_id, ids))


@dataclass
class _FakeClient:
    datasets: _StubDatasets = field(default_factory=_StubDatasets)
    experiments: _StubExperiments = field(default_factory=_StubExperiments)
    params: _StubValuesByExp = field(default_factory=lambda: _StubValuesByExp("set_exp_params"))
    features: _StubValuesByExp = field(default_factory=lambda: _StubValuesByExp("set_exp_features"))
    attributes: _StubValuesByExp = field(default_factory=lambda: _StubValuesByExp("set_exp_attributes"))
    _http: _StubHttp = field(default_factory=_StubHttp)


# ─── Tests ──────────────────────────────────────────────────────────────


def test_purge_absent_dataset_is_noop():
    client = _FakeClient()
    workflows = WorkflowsClient(client)  # type: ignore[arg-type]
    counts = workflows.purge_dataset("does_not_exist")
    assert counts == {
        "datasets": 0, "experiments": 0,
        "params": 0, "features": 0, "attributes": 0,
    }
    assert client._http.deletes == []


def test_purge_dataset_with_experiments_and_values():
    client = _FakeClient()
    client.datasets.by_code["DS/ref"] = _FakeDataset(id=10, code="DS/ref")
    client.experiments.by_dataset[10] = [
        _FakeExperiment(id=100, code="DS/ref/000"),
        _FakeExperiment(id=101, code="DS/ref/001"),
    ]
    # Per-experiment param rows
    client._http.rows_by_table_and_exp = {
        ("set_exp_params", 100): [{"Id": 1000}, {"Id": 1001}, {"Id": 1002}],
        ("set_exp_params", 101): [{"Id": 1010}, {"Id": 1011}],
        ("set_exp_features", 100): [{"Id": 2000}],
        ("set_exp_attributes", 101): [{"Id": 3000}, {"Id": 3001}],
    }

    workflows = WorkflowsClient(client)  # type: ignore[arg-type]
    counts = workflows.purge_dataset("DS/ref")

    assert counts == {
        "datasets": 1, "experiments": 2,
        "params": 5, "features": 1, "attributes": 2,
    }


def test_purge_dataset_deletes_in_correct_order():
    """Values must be removed before experiments, experiments before the dataset."""
    client = _FakeClient()
    client.datasets.by_code["DS/x"] = _FakeDataset(id=20, code="DS/x")
    client.experiments.by_dataset[20] = [_FakeExperiment(id=200, code="DS/x/000")]
    client._http.rows_by_table_and_exp = {
        ("set_exp_params", 200): [{"Id": 5000}],
    }
    workflows = WorkflowsClient(client)  # type: ignore[arg-type]
    workflows.purge_dataset("DS/x")

    delete_tables = [d[0] for d in client._http.deletes]
    # set_exp_params before experiments before datasets
    assert delete_tables.index("set_exp_params") < delete_tables.index("experiments")
    assert delete_tables.index("experiments") < delete_tables.index("datasets")


def test_purge_empty_dataset_still_deletes_dataset_row():
    """Dataset with no experiments still gets removed itself."""
    client = _FakeClient()
    client.datasets.by_code["DS/empty"] = _FakeDataset(id=30, code="DS/empty")
    client.experiments.by_dataset[30] = []
    workflows = WorkflowsClient(client)  # type: ignore[arg-type]
    counts = workflows.purge_dataset("DS/empty")
    assert counts["datasets"] == 1
    assert counts["experiments"] == 0
    delete_tables = [d[0] for d in client._http.deletes]
    assert "datasets" in delete_tables
