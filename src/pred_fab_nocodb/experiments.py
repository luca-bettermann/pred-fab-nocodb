"""Experiments table client."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from ._base import _BaseTableClient
from .errors import NotFoundError
from .schema import ExperimentColumns, Status


@dataclass(frozen=True)
class Experiment:
    """One row from the `experiments` table."""

    id: int
    code: str
    study_id: int
    status: Status
    dataset_id: Optional[int] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    notes: Optional[str] = None


class ExperimentsClient(_BaseTableClient):
    """Read/write the `experiments` table."""

    def get_by_code(self, code: str) -> Experiment:
        """Fetch an experiment by its code (e.g. `'ADVEI_2026_001'`)."""
        rows = self._http.records_list(
            self._table_id,
            where=f"({ExperimentColumns.CODE},eq,{code})",
            limit=1,
        )
        if not rows:
            raise NotFoundError(f"Experiment with code={code!r} not found")
        return _row_to_experiment(rows[0])

    def list_by_study(
        self,
        study_id: int,
        *,
        status: Status | None = None,
    ) -> list[Experiment]:
        """Return every experiment belonging to a study, optionally filtered by status."""
        clauses = [f"({ExperimentColumns.STUDIES},eq,{study_id})"]
        if status is not None:
            clauses.append(f"({ExperimentColumns.STATUS},eq,{status.value})")
        rows = self._http.records_list(self._table_id, where="~and".join(clauses))
        return [_row_to_experiment(r) for r in rows]

    def list_by_dataset(self, dataset_id: int) -> list[Experiment]:
        """Return every experiment belonging to a dataset."""
        rows = self._http.records_list(
            self._table_id,
            where=f"({ExperimentColumns.DATASET},eq,{dataset_id})",
        )
        return [_row_to_experiment(r) for r in rows]

    def upsert(
        self,
        *,
        study_id: int,
        code: str,
        status: Status = Status.DRAFT,
        dataset_id: Optional[int] = None,
        notes: Optional[str] = None,
    ) -> Experiment:
        """Create or update an experiment row, keyed by ``code``.

        If a row with this ``code`` already exists, its non-LTAR fields
        (``status`` and ``notes``) are patched and both link fields
        (``studies`` + ``dataset``) are re-asserted (idempotent). Otherwise
        a new row is inserted.
        """
        body: dict[str, Any] = {ExperimentColumns.STATUS: status.value}
        if notes is not None:
            body[ExperimentColumns.NOTES] = notes

        try:
            existing = self.get_by_code(code)
        except NotFoundError:
            existing = None

        if existing is None:
            insert_body = {ExperimentColumns.CODE: code, **body}
            self._http.records_create(self._table_id, insert_body)
            exp = self.get_by_code(code)
        else:
            update_body = {ExperimentColumns.ID: existing.id, **body}
            self._http.records_update(self._table_id, update_body)
            exp = self.get_by_code(code)

        # Set / re-assert link fields via the /links/ endpoint (idempotent).
        self._link(ExperimentColumns.STUDIES, exp.id, study_id)
        if dataset_id is not None:
            self._link(ExperimentColumns.DATASET, exp.id, dataset_id)
        return exp

    def update_status(self, experiment_id: int, status: Status) -> None:
        """Change an experiment's status."""
        self._http.records_update(
            self._table_id,
            {ExperimentColumns.ID: experiment_id, ExperimentColumns.STATUS: status.value},
        )

    def update_timestamps(
        self,
        experiment_id: int,
        *,
        started_at: Optional[datetime] = None,
        ended_at: Optional[datetime] = None,
    ) -> None:
        """Set the start and/or end timestamps."""
        body: dict[str, Any] = {ExperimentColumns.ID: experiment_id}
        if started_at is not None:
            body[ExperimentColumns.STARTED_AT] = started_at.isoformat()
        if ended_at is not None:
            body[ExperimentColumns.ENDED_AT] = ended_at.isoformat()
        if len(body) == 1:
            return  # nothing to update
        self._http.records_update(self._table_id, body)

    def set_dataset(self, experiment_id: int, dataset_id: Optional[int]) -> None:
        """Assign or clear the experiment's dataset link."""
        self._http.records_update(
            self._table_id,
            {ExperimentColumns.ID: experiment_id, ExperimentColumns.DATASET: dataset_id},
        )


def _row_to_experiment(row: dict[str, Any]) -> Experiment:
    study_id = _resolve_link_id(row.get(ExperimentColumns.STUDIES))
    dataset_id = _resolve_link_id(row.get(ExperimentColumns.DATASET))
    return Experiment(
        id=int(row[ExperimentColumns.ID]),
        code=str(row[ExperimentColumns.CODE]),
        study_id=study_id or 0,
        status=Status(row.get(ExperimentColumns.STATUS, Status.DRAFT.value)),
        dataset_id=dataset_id,
        started_at=_parse_dt(row.get(ExperimentColumns.STARTED_AT)),
        ended_at=_parse_dt(row.get(ExperimentColumns.ENDED_AT)),
        notes=row.get(ExperimentColumns.NOTES),
    )


def _resolve_link_id(value: Any) -> Optional[int]:
    """NocoDB renders linked-record fields as a list of `{Id: ...}` dicts (or
    a bare int / dict depending on response context). Normalise to int|None."""
    if value is None or value == "":
        return None
    if isinstance(value, list):
        if not value:
            return None
        first = value[0]
        if isinstance(first, dict):
            return int(first.get("Id", 0)) or None
        return int(first)
    if isinstance(value, dict):
        return int(value.get("Id", 0)) or None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_dt(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
