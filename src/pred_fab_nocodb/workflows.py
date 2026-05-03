"""High-level workflow helpers — multi-table operations the consumers use repeatedly.

Composes the per-table clients into the typical lbp / fab-script recipes:

- `plan_experiment` (lbp → NocoDB write)
- `load_for_fabrication` (fab script ← NocoDB read)
- `save_fabrication_result` (lbp → NocoDB write)
- `load_dataset` (lbp ← NocoDB read; constructs the bundle for pred-fab Dataset)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Mapping, Optional

from ._projector import project_to_dimension
from ._values import ValueWriteItem
from .schema import Status

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
    trajectory_params: dict[str, list[tuple[dict[str, int], Any]]]
    sparse_trajectories: dict[str, dict[int, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class ExperimentBundle:
    """Bundle returned by `load_dataset` — one per experiment in the dataset."""

    experiment_id: int
    experiment_code: str
    status: Status
    static_params: dict[str, Any]
    trajectory_params: dict[str, list[tuple[dict[str, int], Any]]]
    features: dict[str, list[tuple[dict[str, int], Any]]]
    attributes: dict[str, list[tuple[dict[str, int], Any]]]


@dataclass
class ExperimentPlan:
    """Inputs to `plan_experiment` — declarative description of what to write."""

    static_params: dict[str, Any] = field(default_factory=dict)
    trajectory_params: dict[str, list[tuple[Mapping[str, int], Any]]] = field(default_factory=dict)


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

        `domain` is required if `plan.trajectory_params` is non-empty (used to
        upsert dim_positions for the per-layer values).

        Returns the new experiment id.
        """
        study = self._c.studies.get_by_code(study_code)
        dataset_id: Optional[int] = None
        if dataset_code is not None:
            dataset_id = self._c.datasets.get_by_code(dataset_code).id

        exp = self._c.experiments.create(
            study_id=study.id,
            code=exp_code,
            status=Status.DRAFT,
            dataset_id=dataset_id,
        )

        items: list[ValueWriteItem] = []
        for code, value in plan.static_params.items():
            items.append(ValueWriteItem(value_code=code, value=value))
        if plan.trajectory_params and domain is None:
            raise ValueError("`domain` is required when trajectory_params is non-empty")
        for code, samples in plan.trajectory_params.items():
            for axes, value in samples:
                items.append(
                    ValueWriteItem(
                        value_code=code,
                        value=value,
                        domain=domain,
                        axes=dict(axes),
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
        schedule_dim: Optional[str] = None,
    ) -> FabricationLoad:
        """Read everything a fab script needs; pass ``schedule_dim`` to also project trajectories."""
        exp = self._c.experiments.get_by_code(exp_code)
        constants = self._c.study_constants.read(exp.study_id)
        static = self._c.params.read_static(exp.id)
        trajectory = self._c.params.read_trajectory(exp.id)
        if mark_running:
            self._c.experiments.update_status(exp.id, Status.RUNNING)
            self._c.experiments.update_timestamps(exp.id, started_at=datetime.utcnow())

        sparse: dict[str, dict[int, Any]] = {}
        if schedule_dim is not None:
            sparse = project_to_dimension(trajectory, dimension=schedule_dim)

        return FabricationLoad(
            experiment_id=exp.id,
            experiment_code=exp.code,
            study_id=exp.study_id,
            study_constants=constants,
            static_params=static,
            trajectory_params=trajectory,
            sparse_trajectories=sparse,
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
        experiments = self._c.experiments.list_by_dataset(dataset.id)
        if only_done:
            experiments = [e for e in experiments if e.status == Status.DONE]
        bundles: list[ExperimentBundle] = []
        for exp in experiments:
            bundles.append(
                ExperimentBundle(
                    experiment_id=exp.id,
                    experiment_code=exp.code,
                    status=exp.status,
                    static_params=self._c.params.read_static(exp.id),
                    trajectory_params=self._c.params.read_trajectory(exp.id),
                    features=self._c.features.read_trajectory(exp.id),
                    attributes=self._c.attributes.read_trajectory(exp.id),
                )
            )
        return bundles
