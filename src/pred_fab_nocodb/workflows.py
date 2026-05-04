"""High-level workflow helpers — multi-table operations the consumers use repeatedly.

Composes the per-table clients into the typical lbp / fab-script recipes:

- `plan_experiment` (lbp → NocoDB write)
- `load_for_fabrication` (fab script ← NocoDB read)
- `save_fabrication_result` (lbp → NocoDB write)
- `load_dataset` (lbp ← NocoDB read; constructs the bundle for pred-fab Dataset)

The trajectory shape is pred-fab's :class:`ParameterUpdateEvent` end-to-end:
sparse events with ``(dimension, step_index, updates)``. No nocodb-local
projector / dense rebuild — the storage layer reads/writes the same value
objects pred-fab consumes internally.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from pred_fab.core.events import ParameterUpdateEvent

from ._values import ValueWriteItem
from .errors import NotFoundError
from .schema import (
    AttributeColumns,
    DatasetColumns,
    ExperimentColumns,
    FeatureColumns,
    ParamColumns,
    Status,
)

if TYPE_CHECKING:
    from .client import NocoDBClient


@dataclass(frozen=True)
class FabricationLoad:
    """Payload returned by `load_for_fabrication` — everything a fab script
    needs to run an experiment."""

    experiment_id: int
    experiment_code: str
    study_id: int
    study_constants: dict[str, float]
    static_params: dict[str, Any]
    parameter_updates: list[ParameterUpdateEvent] = field(default_factory=list)

    def as_overrides(self, *, schedule_dim: str) -> dict[str, Any]:
        """Flatten ``study_constants`` + ``static_params`` + per-step trajectory
        values into one dict suitable for ``params.update(load.as_overrides(...))``
        on the fab-script side.

        Trajectory entries are projected onto ``schedule_dim`` and emerge as
        ``{step_index: value}`` dicts per param code — the consumer carries
        forward through unchanged steps. Events whose ``dimension`` doesn't
        match ``schedule_dim`` (or that lack a step index) are dropped.

        Precedence (later wins):
          ``study_constants`` ⟶ ``static_params`` ⟶ per-step trajectory dicts.
        """
        sparse: dict[str, dict[int, Any]] = {}
        for event in self.parameter_updates:
            if event.dimension != schedule_dim or event.step_index is None:
                continue
            for code, value in event.updates.items():
                sparse.setdefault(code, {})[int(event.step_index)] = value
        return {
            **self.study_constants,
            **self.static_params,
            **sparse,
        }


@dataclass(frozen=True)
class ExperimentBundle:
    """Bundle returned by `load_dataset` — one per experiment in the dataset."""

    experiment_id: int
    experiment_code: str
    status: Status
    static_params: dict[str, Any]
    parameter_updates: list[ParameterUpdateEvent]
    features: dict[str, list[tuple[dict[str, int], Any]]]
    attributes: dict[str, list[tuple[dict[str, int], Any]]]


@dataclass
class ExperimentPlan:
    """Inputs to `plan_experiment` — declarative description of what to write.

    ``static_params`` are per-experiment scalars (no schedule).
    ``parameter_updates`` are sparse :class:`ParameterUpdateEvent`s — emit
    only at the first step and at every step where a value changes from the
    previous step. The consumer carry-forwards unchanged values.
    """

    static_params: dict[str, Any] = field(default_factory=dict)
    parameter_updates: list[ParameterUpdateEvent] = field(default_factory=list)


class WorkflowsClient:
    """High-level multi-table operations.

    Constructed by `NocoDBClient` and exposed as `client.workflows`. Composes
    the per-table clients; doesn't add new HTTP capability.
    """

    def __init__(self, client: "NocoDBClient"):
        self._c = client

    # ─── Plan ─────────────────────────────────────────────────────────

    def plan_experiment(
        self,
        *,
        study_code: str,
        exp_code: str,
        plan: ExperimentPlan,
        dataset_code: Optional[str] = None,
        domain: Optional[str] = None,
    ) -> int:
        """Create a draft experiment + write all its parameters in one shot.

        Each :class:`ParameterUpdateEvent` in ``plan.parameter_updates``
        produces one row per ``(value_code, value)`` pair in its ``updates``
        dict, all sharing the dim_position resolved from
        ``{event.dimension: event.step_index}``. ``domain`` is required when
        ``parameter_updates`` is non-empty (the dim_position needs a domain).

        Returns the new experiment id.
        """
        study = self._c.studies.get_by_code(study_code)
        dataset_id: Optional[int] = None
        if dataset_code is not None:
            dataset_id = self._c.datasets.get_by_code(dataset_code).id

        exp = self._c.experiments.upsert(
            study_id=study.id,
            code=exp_code,
            status=Status.DRAFT,
            dataset_id=dataset_id,
        )

        items: list[ValueWriteItem] = []
        for code, value in plan.static_params.items():
            items.append(ValueWriteItem(value_code=code, value=value))
        if plan.parameter_updates and domain is None:
            raise ValueError(
                "`domain` is required when parameter_updates is non-empty"
            )
        for event in plan.parameter_updates:
            if event.dimension is None or event.step_index is None:
                raise ValueError(
                    "parameter_updates entries must set both dimension and "
                    "step_index for nocodb writes "
                    f"(got dimension={event.dimension!r}, "
                    f"step_index={event.step_index!r})"
                )
            axes = {event.dimension: int(event.step_index)}
            for code, value in event.updates.items():
                items.append(
                    ValueWriteItem(
                        value_code=code,
                        value=value,
                        domain=domain,
                        axes=axes,
                    )
                )
        if items:
            self._c.params.write_batch(exp_id=exp.id, exp_code=exp.code, items=items)
        return exp.id

    # ─── Load for fabrication ─────────────────────────────────────────

    def load_for_fabrication(
        self,
        *,
        exp_code: str,
        mark_running: bool = True,
    ) -> FabricationLoad:
        """Read everything a fab script needs.

        Returns a :class:`FabricationLoad` with sparse
        ``parameter_updates``; consumers project to a schedule dimension via
        ``load.as_overrides(schedule_dim=...)``. Optionally transitions the
        experiment from DRAFT to RUNNING with a timestamp (default: yes).
        """
        exp = self._c.experiments.get_by_code(exp_code)
        constants = self._c.study_constants.read(exp.study_code)
        static = self._c.params.read_static(exp.code)
        events = self._c.params.read_parameter_updates(exp.code)
        if mark_running:
            self._c.experiments.update_status(exp.id, Status.RUNNING)
            self._c.experiments.update_timestamps(exp.id, started_at=datetime.utcnow())

        return FabricationLoad(
            experiment_id=exp.id,
            experiment_code=exp.code,
            study_id=exp.study_id,
            study_constants=constants,
            static_params=static,
            parameter_updates=events,
        )

    # ─── Save fabrication result ──────────────────────────────────────

    def save_fabrication_result(
        self,
        *,
        exp_code: str,
        status: Status = Status.DONE,
        features: Optional[list[ValueWriteItem]] = None,
        attributes: Optional[list[ValueWriteItem]] = None,
        ended_at: Optional[datetime] = None,
        notes: Optional[str] = None,
    ) -> None:
        """Write features + attributes, transition status, optionally update notes."""
        exp = self._c.experiments.get_by_code(exp_code)
        if features:
            self._c.features.write_batch(
                exp_id=exp.id, exp_code=exp.code, items=features
            )
        if attributes:
            self._c.attributes.write_batch(
                exp_id=exp.id, exp_code=exp.code, items=attributes
            )
        self._c.experiments.update_status(exp.id, status)
        self._c.experiments.update_timestamps(
            exp.id, ended_at=ended_at or datetime.utcnow()
        )
        if notes is not None:
            # update_status doesn't touch notes; do it via a dedicated patch
            self._c.experiments._http.records_update(  # type: ignore[attr-defined]
                self._c.experiments._table_id,  # type: ignore[attr-defined]
                {"Id": exp.id, "notes": notes},
            )

    # ─── Load dataset ─────────────────────────────────────────────────

    def load_dataset(
        self,
        *,
        dataset_code: str,
        only_done: bool = False,
    ) -> list[ExperimentBundle]:
        """Return one bundle per experiment in the dataset.

        Set `only_done=True` to filter to completed experiments only (useful
        for training-data construction where in-progress runs would be noise).
        """
        dataset = self._c.datasets.get_by_code(dataset_code)
        experiments = self._c.experiments.list_by_dataset(dataset.code)
        if only_done:
            experiments = [e for e in experiments if e.status == Status.DONE]
        bundles: list[ExperimentBundle] = []
        for exp in experiments:
            bundles.append(
                ExperimentBundle(
                    experiment_id=exp.id,
                    experiment_code=exp.code,
                    status=exp.status,
                    static_params=self._c.params.read_static(exp.code),
                    parameter_updates=self._c.params.read_parameter_updates(exp.code),
                    features=self._c.features.read_trajectory(exp.code),
                    attributes=self._c.attributes.read_trajectory(exp.code),
                )
            )
        return bundles

    # ─── Purge ────────────────────────────────────────────────────────

    def purge_dataset(self, dataset_code: str) -> dict[str, int]:
        """Delete a dataset, its experiments, and every per-experiment value row.

        Useful as the cleanup step before a re-plan run with `--overwrite`.
        Idempotent: returns zero-counts and skips if the dataset is absent.
        ``dim_positions`` and ``set_study_constants`` are intentionally
        untouched — they may be referenced by other datasets in the same
        study, and re-creating them on the next plan is wasteful.

        Returns the number of rows removed per table — useful for logging.
        """
        counts = {
            "datasets": 0,
            "experiments": 0,
            "params": 0,
            "features": 0,
            "attributes": 0,
        }
        try:
            dataset = self._c.datasets.get_by_code(dataset_code)
        except NotFoundError:
            return counts

        experiments = self._c.experiments.list_by_dataset(dataset.code)

        # Cascade: per-experiment value rows first, then the experiments,
        # then the dataset row itself.
        for exp in experiments:
            counts["params"] += self._delete_values_for_exp(
                self._c.params._table_id, exp.code, ParamColumns.EXPERIMENT,
            )
            counts["features"] += self._delete_values_for_exp(
                self._c.features._table_id, exp.code, FeatureColumns.EXPERIMENT,
            )
            counts["attributes"] += self._delete_values_for_exp(
                self._c.attributes._table_id, exp.code, AttributeColumns.EXPERIMENT,
            )

        if experiments:
            self._c._http.records_delete(
                self._c.experiments._table_id,
                [{ExperimentColumns.ID: e.id} for e in experiments],
            )
            counts["experiments"] = len(experiments)

        self._c._http.records_delete(
            self._c.datasets._table_id,
            {DatasetColumns.ID: dataset.id},
        )
        counts["datasets"] = 1
        return counts

    def _delete_values_for_exp(
        self,
        table_id: str,
        exp_code: str,
        experiment_column: str,
    ) -> int:
        """Bulk-delete every set_exp_* row whose experiment LTAR == exp_code."""
        rows = self._c._http.records_list(
            table_id,
            where=f"({experiment_column},eq,{exp_code})",
        )
        if not rows:
            return 0
        self._c._http.records_delete(
            table_id,
            [{"Id": int(r["Id"])} for r in rows],
        )
        return len(rows)


