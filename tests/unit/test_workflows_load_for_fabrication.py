"""Tests for WorkflowsClient.load_for_fabrication, focused on sparse projection."""
from dataclasses import dataclass, field
from typing import Any

import pytest

from pred_fab_nocodb.errors import ValidationError
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


# ─── No schedule_dim → unchanged behaviour ──────────────────────────────


def test_load_for_fabrication_default_returns_empty_sparse_trajectories():
    client = _FakeClient()
    _seed_basic(client)
    workflows = WorkflowsClient(client)  # type: ignore[arg-type]
    load = workflows.load_for_fabrication(exp_code="exp1", mark_running=False)
    assert load.sparse_trajectories == {}
    # Raw sparse form (with full axes dicts) preserved
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


# ─── With schedule_dim → populated sparse_trajectories ──────────────────


def test_load_for_fabrication_with_schedule_dim_populates_sparse_trajectories():
    client = _FakeClient()
    _seed_basic(client)
    workflows = WorkflowsClient(client)  # type: ignore[arg-type]
    load = workflows.load_for_fabrication(
        exp_code="exp1",
        mark_running=False,
        schedule_dim="layer_idx",
    )
    assert load.sparse_trajectories == {
        "print_speed": {0: 0.005, 3: 0.006, 7: 0.008},
    }
    # Raw sparse form (with full axes dicts) remains intact alongside
    assert load.trajectory_params["print_speed"]


def test_sparse_trajectories_empty_when_no_trajectory_params():
    """A study with only static params should yield an empty sparse dict, not error."""
    client = _FakeClient()
    client.experiments.by_code["exp1"] = _FakeExp(id=1, code="exp1", study_id=42)
    client.params.static[1] = {"path_offset": 1.5}
    workflows = WorkflowsClient(client)  # type: ignore[arg-type]
    load = workflows.load_for_fabrication(
        exp_code="exp1",
        mark_running=False,
        schedule_dim="layer_idx",
    )
    assert load.sparse_trajectories == {}


def test_load_for_fabrication_propagates_validation_errors():
    """A trajectory entry missing the schedule dimension surfaces ValidationError."""
    client = _FakeClient()
    client.experiments.by_code["exp1"] = _FakeExp(id=1, code="exp1", study_id=42)
    client.params.trajectory[1] = {"speed": [({"node_idx": 0}, 0.005)]}
    workflows = WorkflowsClient(client)  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="missing dimension"):
        workflows.load_for_fabrication(
            exp_code="exp1", mark_running=False, schedule_dim="layer_idx",
        )


# ─── FabricationLoad.as_overrides ───────────────────────────────────────


def test_as_overrides_merges_constants_static_and_sparse():
    client = _FakeClient()
    _seed_basic(client)  # static + trajectory
    client.study_constants.by_study[42] = {"component_height": 25, "water_ratio": 0.25}
    workflows = WorkflowsClient(client)  # type: ignore[arg-type]
    load = workflows.load_for_fabrication(
        exp_code="exp1", mark_running=False, schedule_dim="layer_idx",
    )
    overrides = load.as_overrides()
    # Constants present
    assert overrides["component_height"] == 25
    assert overrides["water_ratio"] == 0.25
    # Static present
    assert overrides["path_offset"] == 1.5
    assert overrides["layer_height"] == 3.0
    # Sparse trajectory present, in {step: value} shape
    assert overrides["print_speed"] == {0: 0.005, 3: 0.006, 7: 0.008}


def test_as_overrides_precedence_trajectory_over_static_over_constants():
    """Same key in multiple buckets: trajectory > static > constants."""
    client = _FakeClient()
    client.experiments.by_code["exp1"] = _FakeExp(id=1, code="exp1", study_id=42)
    client.study_constants.by_study[42] = {"shared": "from_constants"}
    client.params.static[1] = {"shared": "from_static"}
    client.params.trajectory[1] = {
        "shared": [({"layer_idx": 0}, "from_trajectory")],
    }
    workflows = WorkflowsClient(client)  # type: ignore[arg-type]
    load = workflows.load_for_fabrication(
        exp_code="exp1", mark_running=False, schedule_dim="layer_idx",
    )
    overrides = load.as_overrides()
    # Trajectory wins (it's a dict, not the constant string)
    assert overrides["shared"] == {0: "from_trajectory"}


def test_as_overrides_with_no_sparse_returns_constants_plus_static_only():
    client = _FakeClient()
    _seed_basic(client)
    client.study_constants.by_study[42] = {"component_height": 25}
    workflows = WorkflowsClient(client)  # type: ignore[arg-type]
    # No schedule_dim → sparse_trajectories empty
    load = workflows.load_for_fabrication(exp_code="exp1", mark_running=False)
    overrides = load.as_overrides()
    assert overrides["component_height"] == 25
    assert overrides["path_offset"] == 1.5
    # `print_speed` not in overrides since sparse is empty
    assert "print_speed" not in overrides
