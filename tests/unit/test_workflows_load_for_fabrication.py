"""Tests for WorkflowsClient.load_for_fabrication, focused on densification."""
from dataclasses import dataclass, field
from typing import Any

import pytest

from pred_fab_nocodb.workflows import WorkflowsClient


@dataclass
class _FakeExp:
    id: int
    code: str
    study_id: int


@dataclass
class _ExperimentsStub:
    by_code: dict[str, _FakeExp] = field(default_factory=dict)
    status_calls: list[tuple[int, Any]] = field(default_factory=list)
    timestamp_calls: list[int] = field(default_factory=list)

    def get_by_code(self, code: str) -> _FakeExp:
        return self.by_code[code]

    def update_status(self, exp_id: int, status: Any) -> None:
        self.status_calls.append((exp_id, status))

    def update_timestamps(self, exp_id: int, **kwargs: Any) -> None:
        self.timestamp_calls.append(exp_id)


@dataclass
class _StudyConstantsStub:
    by_study: dict[int, dict[str, float]] = field(default_factory=dict)

    def read(self, study_id: int) -> dict[str, float]:
        return self.by_study.get(study_id, {})


@dataclass
class _ParamsStub:
    static: dict[int, dict[str, Any]] = field(default_factory=dict)
    trajectory: dict[int, dict[str, list[tuple[dict[str, int], Any]]]] = field(default_factory=dict)

    def read_static(self, exp_id: int) -> dict[str, Any]:
        return self.static.get(exp_id, {})

    def read_trajectory(self, exp_id: int) -> dict[str, list[tuple[dict[str, int], Any]]]:
        return self.trajectory.get(exp_id, {})


@dataclass
class _FakeClient:
    experiments: _ExperimentsStub = field(default_factory=_ExperimentsStub)
    study_constants: _StudyConstantsStub = field(default_factory=_StudyConstantsStub)
    params: _ParamsStub = field(default_factory=_ParamsStub)


def _seed_basic(client: _FakeClient) -> None:
    client.experiments.by_code["exp1"] = _FakeExp(id=1, code="exp1", study_id=42)
    client.study_constants.by_study[42] = {"design_height_mm": 30.0}
    client.params.static[1] = {"path_offset": 1.5, "layer_height": 3.0}
    client.params.trajectory[1] = {
        "print_speed": [
            ({"layer_idx": 0}, 0.005),
            ({"layer_idx": 3}, 0.006),
            ({"layer_idx": 7}, 0.008),
        ],
    }


# ─── No densify args → unchanged behaviour ──────────────────────────────


def test_load_for_fabrication_default_returns_empty_dense_trajectories():
    client = _FakeClient()
    _seed_basic(client)
    workflows = WorkflowsClient(client)  # type: ignore[arg-type]
    load = workflows.load_for_fabrication(exp_code="exp1", mark_running=False)
    assert load.dense_trajectories == {}
    # Sparse form preserved
    assert "print_speed" in load.trajectory_params
    assert len(load.trajectory_params["print_speed"]) == 3


def test_load_for_fabrication_default_preserves_other_payload():
    client = _FakeClient()
    _seed_basic(client)
    workflows = WorkflowsClient(client)  # type: ignore[arg-type]
    load = workflows.load_for_fabrication(exp_code="exp1", mark_running=False)
    assert load.experiment_id == 1
    assert load.experiment_code == "exp1"
    assert load.study_id == 42
    assert load.study_constants == {"design_height_mm": 30.0}
    assert load.static_params == {"path_offset": 1.5, "layer_height": 3.0}


# ─── With densify args → populated dense_trajectories ───────────────────


def test_load_for_fabrication_with_densify_populates_dense_trajectories():
    client = _FakeClient()
    _seed_basic(client)
    workflows = WorkflowsClient(client)  # type: ignore[arg-type]
    load = workflows.load_for_fabrication(
        exp_code="exp1",
        mark_running=False,
        densify_dim="layer_idx",
        n_steps=10,
    )
    assert load.dense_trajectories == {
        "print_speed": [0.005, 0.005, 0.005, 0.006, 0.006, 0.006, 0.006, 0.008, 0.008, 0.008],
    }
    # Sparse form remains intact alongside the dense form
    assert load.trajectory_params["print_speed"]


def test_dense_trajectories_lengths_match_n_steps():
    client = _FakeClient()
    _seed_basic(client)
    workflows = WorkflowsClient(client)  # type: ignore[arg-type]
    load = workflows.load_for_fabrication(
        exp_code="exp1",
        mark_running=False,
        densify_dim="layer_idx",
        n_steps=15,
    )
    for code, values in load.dense_trajectories.items():
        assert len(values) == 15, f"{code} length {len(values)} != 15"


def test_dense_trajectories_empty_when_no_trajectory_params():
    """A study with only static params should yield an empty dense dict, not error."""
    client = _FakeClient()
    client.experiments.by_code["exp1"] = _FakeExp(id=1, code="exp1", study_id=42)
    client.params.static[1] = {"path_offset": 1.5}
    workflows = WorkflowsClient(client)  # type: ignore[arg-type]
    load = workflows.load_for_fabrication(
        exp_code="exp1",
        mark_running=False,
        densify_dim="layer_idx",
        n_steps=5,
    )
    assert load.dense_trajectories == {}


# ─── Argument-pairing validation ────────────────────────────────────────


def test_load_for_fabrication_rejects_densify_dim_without_n_steps():
    client = _FakeClient()
    _seed_basic(client)
    workflows = WorkflowsClient(client)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="must be supplied together"):
        workflows.load_for_fabrication(
            exp_code="exp1", mark_running=False, densify_dim="layer_idx",
        )


def test_load_for_fabrication_rejects_n_steps_without_densify_dim():
    client = _FakeClient()
    _seed_basic(client)
    workflows = WorkflowsClient(client)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="must be supplied together"):
        workflows.load_for_fabrication(
            exp_code="exp1", mark_running=False, n_steps=5,
        )
