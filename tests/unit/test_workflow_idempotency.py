"""End-to-end idempotency tests for the high-level workflows.

Each writeable primitive in pred-fab-nocodb is unit-tested for idempotency
in isolation (`upsert`, `write`, `write_batch`, `get_or_create`). These
tests prove the property survives composition: running a full workflow
against the same `FakeNocoDBHttp` workspace twice with identical inputs
must leave the same number of rows in every table — no duplicates, no
orphans.

Field VALUE mutations on existing rows (timestamps, status transitions)
are allowed; the assertion is structural — row counts per table.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from pred_fab_nocodb.datasets import DatasetsClient
from pred_fab_nocodb.dim_positions import DimPositionsClient
from pred_fab_nocodb.experiments import ExperimentsClient
from pred_fab_nocodb.schema import (
    AttributeColumns,
    FeatureColumns,
    ParamColumns,
    Purpose,
    Status,
    Strategy,
    StudyColumns,
    Tables,
)
from pred_fab_nocodb.studies import StudiesClient
from pred_fab_nocodb.study_constants import StudyConstantsClient
from pred_fab_nocodb import ParameterUpdateEvent
from pred_fab_nocodb._values import ValueClient, ValueWriteItem
from pred_fab_nocodb.workflows import (
    ExperimentPlan,
    WorkflowsClient,
)


# ─── Workspace fixture ──────────────────────────────────────────────────


@dataclass
class _Workspace:
    """Container exposing all sub-clients backed by the same FakeNocoDBHttp,
    with the right shape for `WorkflowsClient(client)` to consume."""

    studies: StudiesClient
    experiments: ExperimentsClient
    datasets: DatasetsClient
    dim_positions: DimPositionsClient
    study_constants: StudyConstantsClient
    params: ValueClient
    features: ValueClient
    attributes: ValueClient
    workflows: WorkflowsClient
    _http: Any  # the shared FakeNocoDBHttp


_LINK_FIELDS: dict[tuple[str, str], str] = {
    (Tables.DATASETS, "study"): "fld_dataset_study",
    (Tables.EXPERIMENTS, "studies"): "fld_exp_studies",
    (Tables.EXPERIMENTS, "dataset"): "fld_exp_dataset",
    (Tables.SET_STUDY_CONSTANTS, "study"): "fld_const_study",
    (Tables.SET_EXP_PARAMS, "experiment"): "fld_param_exp",
    (Tables.SET_EXP_PARAMS, "dim"): "fld_param_dim",
    (Tables.SET_EXP_FEATURES, "experiment"): "fld_feat_exp",
    (Tables.SET_EXP_FEATURES, "dim"): "fld_feat_dim",
    (Tables.SET_EXP_ATTRIBUTES, "experiment"): "fld_attr_exp",
    (Tables.SET_EXP_ATTRIBUTES, "dim"): "fld_attr_dim",
}


@pytest.fixture
def workspace(fake_http) -> _Workspace:
    """Pre-build a complete fake NocoDB workspace with seeded studies row."""
    # Initialise every required table empty.
    for table in (
        Tables.STUDIES, Tables.EXPERIMENTS, Tables.DATASETS,
        Tables.DIM_POSITIONS, Tables.SET_STUDY_CONSTANTS,
        Tables.SET_EXP_PARAMS, Tables.SET_EXP_FEATURES, Tables.SET_EXP_ATTRIBUTES,
    ):
        fake_http.set_records(table, [])

    # Register link-field columns so reads after a /links/ call see the FK.
    for (table_name, col), fld_id in _LINK_FIELDS.items():
        fake_http.set_link_field(table_name, fld_id, col)

    def _link_subset(table_name: str) -> dict[str, str]:
        return {
            col: fld_id
            for (tn, col), fld_id in _LINK_FIELDS.items()
            if tn == table_name
        }

    studies = StudiesClient(
        fake_http, base_id="b1", table_id=Tables.STUDIES,
        link_field_ids=_link_subset(Tables.STUDIES),
    )
    experiments = ExperimentsClient(
        fake_http, base_id="b1", table_id=Tables.EXPERIMENTS,
        link_field_ids=_link_subset(Tables.EXPERIMENTS),
    )
    datasets = DatasetsClient(
        fake_http, base_id="b1", table_id=Tables.DATASETS,
        link_field_ids=_link_subset(Tables.DATASETS),
    )
    dim_positions = DimPositionsClient(
        fake_http, base_id="b1", table_id=Tables.DIM_POSITIONS,
    )
    study_constants = StudyConstantsClient(
        fake_http, base_id="b1", table_id=Tables.SET_STUDY_CONSTANTS,
        link_field_ids=_link_subset(Tables.SET_STUDY_CONSTANTS),
    )
    params = ValueClient(
        fake_http, base_id="b1", table_id=Tables.SET_EXP_PARAMS,
        fk_code_column=ParamColumns.PARAM, dim_client=dim_positions,
        link_field_ids=_link_subset(Tables.SET_EXP_PARAMS),
    )
    features = ValueClient(
        fake_http, base_id="b1", table_id=Tables.SET_EXP_FEATURES,
        fk_code_column=FeatureColumns.FEATURE, dim_client=dim_positions,
        link_field_ids=_link_subset(Tables.SET_EXP_FEATURES),
    )
    attributes = ValueClient(
        fake_http, base_id="b1", table_id=Tables.SET_EXP_ATTRIBUTES,
        fk_code_column=AttributeColumns.ATTRIBUTE, dim_client=dim_positions,
        link_field_ids=_link_subset(Tables.SET_EXP_ATTRIBUTES),
    )

    # Create the study row so workflows can resolve study_code lookups.
    studies.upsert(code="ADVEI_2026", description="test study")

    ws = _Workspace(
        studies=studies, experiments=experiments, datasets=datasets,
        dim_positions=dim_positions, study_constants=study_constants,
        params=params, features=features, attributes=attributes,
        workflows=None,  # type: ignore[arg-type]
        _http=fake_http,
    )
    ws.workflows = WorkflowsClient(ws)  # type: ignore[arg-type]
    return ws


def _row_counts(ws: _Workspace) -> dict[str, int]:
    """Snapshot row count per table."""
    return {
        table: len(ws._http.get_records(table))
        for table in (
            Tables.STUDIES, Tables.EXPERIMENTS, Tables.DATASETS,
            Tables.DIM_POSITIONS, Tables.SET_STUDY_CONSTANTS,
            Tables.SET_EXP_PARAMS, Tables.SET_EXP_FEATURES, Tables.SET_EXP_ATTRIBUTES,
        )
    }


# ─── Idempotency tests ──────────────────────────────────────────────────


def test_push_schema_and_constants_idempotent(workspace):
    """`studies.push_schema` + `study_constants.write_batch` are each idempotent;
    composed they leave NocoDB in a stable state across repeated calls."""
    schema = {"schema_id": "ADVEI_2026", "parameters": {"V_fab": [0.005, 0.01]}}
    constants = {"W_filament": 0.007, "component_height_mm": 25.0}
    study = workspace.studies.get_by_code("ADVEI_2026")

    def _push() -> None:
        workspace.studies.push_schema(study.id, schema)
        workspace.study_constants.write_batch(
            study_id=study.id, study_code="ADVEI_2026", constants=constants,
        )

    _push()
    after_first = _row_counts(workspace)
    _push()
    after_second = _row_counts(workspace)

    assert after_first == after_second
    assert after_second[Tables.STUDIES] == 1
    assert after_second[Tables.SET_STUDY_CONSTANTS] == 2

    # And the schema JSON itself is exactly what we pushed (no merge with stale state).
    studies_rows = workspace._http.get_records(Tables.STUDIES)
    import json
    assert json.loads(studies_rows[0][StudyColumns.SCHEMA]) == schema


def test_plan_experiment_idempotent(workspace):
    workspace.datasets.upsert(
        study_id=workspace.studies.get_by_code("ADVEI_2026").id,
        study_code="ADVEI_2026",
        name="reference",
        strategy=Strategy.GRID,
        purpose=Purpose.REFERENCE,
    )

    plan = ExperimentPlan(
        static_params={"calibrationFactor": 1.9, "H_layer": 2.5},
        parameter_updates=[
            ParameterUpdateEvent(
                updates={"V_fab": 0.005}, dimension="layer_idx", step_index=0,
            ),
            ParameterUpdateEvent(
                updates={"V_fab": 0.006}, dimension="layer_idx", step_index=1,
            ),
            ParameterUpdateEvent(
                updates={"V_fab": 0.007}, dimension="layer_idx", step_index=2,
            ),
        ],
    )
    workspace.workflows.plan_experiment(
        study_code="ADVEI_2026",
        exp_code="ADVEI_2026/reference/000",
        plan=plan,
        dataset_code="ADVEI_2026/reference",
        domain="structural",
    )
    after_first = _row_counts(workspace)

    workspace.workflows.plan_experiment(
        study_code="ADVEI_2026",
        exp_code="ADVEI_2026/reference/000",
        plan=plan,
        dataset_code="ADVEI_2026/reference",
        domain="structural",
    )
    after_second = _row_counts(workspace)

    assert after_first == after_second
    # Specifically: 1 experiment, 2 static + 3 trajectory = 5 param rows, 3 dim_positions.
    assert after_second[Tables.EXPERIMENTS] == 1
    assert after_second[Tables.SET_EXP_PARAMS] == 5
    assert after_second[Tables.DIM_POSITIONS] == 3
    assert after_second[Tables.DATASETS] == 1


def test_save_fabrication_result_idempotent(workspace):
    # Need an experiment to attach results to.
    workspace.datasets.upsert(
        study_id=workspace.studies.get_by_code("ADVEI_2026").id,
        study_code="ADVEI_2026", name="reference",
        strategy=Strategy.GRID, purpose=Purpose.REFERENCE,
    )
    workspace.experiments.upsert(
        study_id=workspace.studies.get_by_code("ADVEI_2026").id,
        code="ADVEI_2026/reference/000",
        dataset_id=workspace.datasets.get_by_code("ADVEI_2026/reference").id,
    )

    features = [
        ValueWriteItem(
            value_code="filament_width", value=0.0072,
            domain="structural", axes={"layer_idx": 0, "node_idx": 0},
        ),
        ValueWriteItem(
            value_code="filament_width", value=0.0068,
            domain="structural", axes={"layer_idx": 0, "node_idx": 1},
        ),
    ]
    attributes = [
        ValueWriteItem(value_code="material_deposition", value=0.85),
    ]

    workspace.workflows.save_fabrication_result(
        exp_code="ADVEI_2026/reference/000",
        features=features, attributes=attributes,
    )
    after_first = _row_counts(workspace)

    workspace.workflows.save_fabrication_result(
        exp_code="ADVEI_2026/reference/000",
        features=features, attributes=attributes,
    )
    after_second = _row_counts(workspace)

    assert after_first == after_second
    assert after_second[Tables.SET_EXP_FEATURES] == 2
    assert after_second[Tables.SET_EXP_ATTRIBUTES] == 1


def test_full_round_trip_idempotent(workspace):
    """push_schema (+ constants) -> plan_experiment -> save_fabrication_result, twice."""
    schema = {"schema_id": "ADVEI_2026"}
    constants = {"W_filament": 0.007}
    plan = ExperimentPlan(
        static_params={"calibrationFactor": 1.9, "H_layer": 2.5},
        parameter_updates=[
            ParameterUpdateEvent(
                updates={"V_fab": 0.005}, dimension="layer_idx", step_index=0,
            ),
            ParameterUpdateEvent(
                updates={"V_fab": 0.006}, dimension="layer_idx", step_index=1,
            ),
        ],
    )
    features = [
        ValueWriteItem(
            value_code="filament_width", value=0.0072,
            domain="structural", axes={"layer_idx": 0, "node_idx": 0},
        ),
    ]
    attributes = [
        ValueWriteItem(value_code="material_deposition", value=0.85),
    ]

    def _run() -> None:
        study = workspace.studies.get_by_code("ADVEI_2026")
        workspace.studies.push_schema(study.id, schema)
        workspace.study_constants.write_batch(
            study_id=study.id, study_code="ADVEI_2026", constants=constants,
        )
        workspace.datasets.upsert(
            study_id=workspace.studies.get_by_code("ADVEI_2026").id,
            study_code="ADVEI_2026", name="reference",
            strategy=Strategy.GRID, purpose=Purpose.REFERENCE,
        )
        workspace.workflows.plan_experiment(
            study_code="ADVEI_2026",
            exp_code="ADVEI_2026/reference/000",
            plan=plan,
            dataset_code="ADVEI_2026/reference",
            domain="structural",
        )
        workspace.workflows.save_fabrication_result(
            exp_code="ADVEI_2026/reference/000",
            features=features, attributes=attributes,
        )

    _run()
    after_first = _row_counts(workspace)

    _run()
    after_second = _row_counts(workspace)

    assert after_first == after_second, (
        "Re-running the full workflow created additional rows somewhere — "
        "duplicated state. Diff: " + repr({
            t: (after_first[t], after_second[t])
            for t in after_first if after_first[t] != after_second[t]
        })
    )
