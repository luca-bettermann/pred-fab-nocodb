"""Tests for WorkflowsClient.load_for_fabrication and FabricationLoad.as_overrides."""
from dataclasses import dataclass, field
from typing import Any

from pred_fab_nocodb.events import ParameterUpdateEvent
from pred_fab_nocodb.workflows import WorkflowsClient


@dataclass
class _FakeExp:
    id: int
    code: str
    study_id: int
    study_code: str = ""


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
    by_study_code: dict[str, dict[str, float]] = field(default_factory=dict)

    def read(self, study_code: str) -> dict[str, float]:
        return self.by_study_code.get(study_code, {})


@dataclass
class _ParamsStub:
    static: dict[str, dict[str, Any]] = field(default_factory=dict)
    events: dict[str, list[ParameterUpdateEvent]] = field(default_factory=dict)

    def read_static(self, exp_code: str) -> dict[str, Any]:
        return self.static.get(exp_code, {})

    def read_parameter_updates(self, exp_code: str) -> list[ParameterUpdateEvent]:
        return list(self.events.get(exp_code, []))


@dataclass
class _FakeClient:
    experiments: _ExperimentsStub = field(default_factory=_ExperimentsStub)
    study_constants: _StudyConstantsStub = field(default_factory=_StudyConstantsStub)
    params: _ParamsStub = field(default_factory=_ParamsStub)


def _seed_basic(client: _FakeClient) -> None:
    client.experiments.by_code["exp1"] = _FakeExp(
        id=1, code="exp1", study_id=42, study_code="study_42",
    )
    client.study_constants.by_study_code["study_42"] = {"design_height_mm": 30.0}
    client.params.static["exp1"] = {"path_offset": 1.5, "layer_height": 3.0}
    client.params.events["exp1"] = [
        ParameterUpdateEvent(
            updates={"print_speed": 0.005}, dimension="layer_idx", step_index=0,
        ),
        ParameterUpdateEvent(
            updates={"print_speed": 0.006}, dimension="layer_idx", step_index=3,
        ),
        ParameterUpdateEvent(
            updates={"print_speed": 0.008}, dimension="layer_idx", step_index=7,
        ),
    ]


# ─── load_for_fabrication ──────────────────────────────────────────────────


def test_load_for_fabrication_returns_static_constants_and_events():
    client = _FakeClient()
    _seed_basic(client)
    workflows = WorkflowsClient(client)  # type: ignore[arg-type]
    load = workflows.load_for_fabrication(exp_code="exp1", mark_running=False)
    assert load.experiment_id == 1
    assert load.experiment_code == "exp1"
    assert load.study_id == 42
    assert load.study_constants == {"design_height_mm": 30.0}
    assert load.static_params == {"path_offset": 1.5, "layer_height": 3.0}
    assert len(load.parameter_updates) == 3
    assert {e.step_index for e in load.parameter_updates} == {0, 3, 7}
    assert all(e.dimension == "layer_idx" for e in load.parameter_updates)


def test_load_for_fabrication_empty_events_when_no_trajectory():
    client = _FakeClient()
    client.experiments.by_code["exp1"] = _FakeExp(
        id=1, code="exp1", study_id=42, study_code="study_42",
    )
    client.params.static["exp1"] = {"path_offset": 1.5}
    workflows = WorkflowsClient(client)  # type: ignore[arg-type]
    load = workflows.load_for_fabrication(exp_code="exp1", mark_running=False)
    assert load.parameter_updates == []


# ─── FabricationLoad.as_overrides ───────────────────────────────────────


def test_as_overrides_merges_constants_static_and_per_step_trajectory():
    client = _FakeClient()
    _seed_basic(client)  # static + events
    client.study_constants.by_study_code["study_42"] = {
        "component_height": 25, "water_ratio": 0.25,
    }
    workflows = WorkflowsClient(client)  # type: ignore[arg-type]
    load = workflows.load_for_fabrication(exp_code="exp1", mark_running=False)
    overrides = load.as_overrides(schedule_dim="layer_idx")
    assert overrides["component_height"] == 25
    assert overrides["water_ratio"] == 0.25
    assert overrides["path_offset"] == 1.5
    assert overrides["layer_height"] == 3.0
    assert overrides["print_speed"] == {0: 0.005, 3: 0.006, 7: 0.008}


def test_as_overrides_precedence_trajectory_over_static_over_constants():
    client = _FakeClient()
    client.experiments.by_code["exp1"] = _FakeExp(
        id=1, code="exp1", study_id=42, study_code="study_42",
    )
    client.study_constants.by_study_code["study_42"] = {"shared": "from_constants"}
    client.params.static["exp1"] = {"shared": "from_static"}
    client.params.events["exp1"] = [
        ParameterUpdateEvent(
            updates={"shared": "from_trajectory"},
            dimension="layer_idx",
            step_index=0,
        ),
    ]
    workflows = WorkflowsClient(client)  # type: ignore[arg-type]
    load = workflows.load_for_fabrication(exp_code="exp1", mark_running=False)
    overrides = load.as_overrides(schedule_dim="layer_idx")
    assert overrides["shared"] == {0: "from_trajectory"}


def test_as_overrides_drops_events_for_other_dimensions():
    """`schedule_dim='layer_idx'` filters out events along other axes."""
    client = _FakeClient()
    client.experiments.by_code["exp1"] = _FakeExp(
        id=1, code="exp1", study_id=42, study_code="study_42",
    )
    client.params.static["exp1"] = {"path_offset": 1.5}
    client.params.events["exp1"] = [
        ParameterUpdateEvent(
            updates={"foo": 1.0}, dimension="layer_idx", step_index=0,
        ),
        ParameterUpdateEvent(
            updates={"bar": 2.0}, dimension="time_s", step_index=10,
        ),
    ]
    workflows = WorkflowsClient(client)  # type: ignore[arg-type]
    load = workflows.load_for_fabrication(exp_code="exp1", mark_running=False)
    overrides = load.as_overrides(schedule_dim="layer_idx")
    assert overrides["foo"] == {0: 1.0}
    assert "bar" not in overrides


def test_as_overrides_with_no_events_returns_constants_plus_static_only():
    client = _FakeClient()
    client.experiments.by_code["exp1"] = _FakeExp(
        id=1, code="exp1", study_id=42, study_code="study_42",
    )
    client.study_constants.by_study_code["study_42"] = {"component_height": 25}
    client.params.static["exp1"] = {"path_offset": 1.5}
    workflows = WorkflowsClient(client)  # type: ignore[arg-type]
    load = workflows.load_for_fabrication(exp_code="exp1", mark_running=False)
    overrides = load.as_overrides(schedule_dim="layer_idx")
    assert overrides["component_height"] == 25
    assert overrides["path_offset"] == 1.5
    assert "print_speed" not in overrides
