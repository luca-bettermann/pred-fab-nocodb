"""Experiments table client."""
from __future__ import annotations

import json
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
    study_code: str
    status: Status
    dataset_id: Optional[int] = None
    dataset_code: Optional[str] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    notes: Optional[str] = None
    design: Optional[str] = None  # generative provenance axis (Strategy value)
    provenance: Optional[dict[str, Any]] = None  # full generative config snapshot


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
        study_code: str,
        *,
        status: Status | None = None,
    ) -> list[Experiment]:
        """Return every experiment belonging to a study, optionally filtered by status."""
        clauses = [f"({ExperimentColumns.STUDIES},eq,{study_code})"]
        if status is not None:
            clauses.append(f"({ExperimentColumns.STATUS},eq,{status.value})")
        rows = self._http.records_list(self._table_id, where="~and".join(clauses))
        return [_row_to_experiment(r) for r in rows]

    def list_by_dataset(self, dataset_code: str) -> list[Experiment]:
        """Return every experiment belonging to a dataset."""
        rows = self._http.records_list(
            self._table_id,
            where=f"({ExperimentColumns.DATASET},eq,{dataset_code})",
        )
        return [_row_to_experiment(r) for r in rows]

    def list_codes(self, dataset: str | None = None) -> list[str]:
        """Every experiment code (code column only). ``dataset`` restricts by
        code-prefix namespace (``'reference'`` → ``'reference/004'``), mirroring
        pred-fab's ``Dataset.populate`` — distinct from ``list_by_dataset``'s
        LTAR-link filter."""
        rows = self._http.records_list(self._table_id, fields=[ExperimentColumns.CODE])
        codes = [str(r[ExperimentColumns.CODE]) for r in rows]
        if dataset is not None:
            codes = [c for c in codes if c.startswith(f"{dataset}/") or f"/{dataset}/" in c]
        return codes

    def upsert(
        self,
        *,
        study_id: int,
        code: str,
        status: Status = Status.DRAFT,
        dataset_id: Optional[int] = None,
        notes: Optional[str] = None,
        design: Optional[str] = None,
        provenance: Optional[dict[str, Any]] = None,
    ) -> Experiment:
        """Create or update an experiment row, keyed by ``code``.

        If a row with this ``code`` already exists, its non-LTAR fields
        (``status``, ``notes``, ``design``, ``provenance``) are patched and both
        link fields (``studies`` + ``dataset``) are re-asserted (idempotent).
        Otherwise a new row is inserted.

        ``design`` is the generative provenance axis (a :class:`Strategy` value);
        ``provenance`` is the full generative config snapshot, stored as JSON in the
        ``provenance`` LongText column.
        """
        body: dict[str, Any] = {ExperimentColumns.STATUS: status.value}
        if notes is not None:
            body[ExperimentColumns.NOTES] = notes
        if design is not None:
            body[ExperimentColumns.DESIGN] = design
        if provenance is not None:
            body[ExperimentColumns.PROVENANCE] = json.dumps(provenance)

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
    study_code = _resolve_link_code(row.get(ExperimentColumns.STUDIES))
    dataset_id = _resolve_link_id(row.get(ExperimentColumns.DATASET))
    dataset_code = _resolve_link_code(row.get(ExperimentColumns.DATASET))
    return Experiment(
        id=int(row[ExperimentColumns.ID]),
        code=str(row[ExperimentColumns.CODE]),
        study_id=study_id or 0,
        study_code=study_code or "",
        status=Status(row.get(ExperimentColumns.STATUS, Status.DRAFT.value)),
        dataset_id=dataset_id,
        dataset_code=dataset_code,
        started_at=_parse_dt(row.get(ExperimentColumns.STARTED_AT)),
        ended_at=_parse_dt(row.get(ExperimentColumns.ENDED_AT)),
        notes=row.get(ExperimentColumns.NOTES),
        design=row.get(ExperimentColumns.DESIGN) or None,
        provenance=_parse_provenance(row.get(ExperimentColumns.PROVENANCE)),
    )


def _parse_provenance(value: Any) -> Optional[dict[str, Any]]:
    """Deserialize the ``provenance`` LongText (JSON) column to a dict; None if blank
    or unparseable (already a dict passes through, for response-shape robustness)."""
    if value is None or value == "":
        return None
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


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


def _resolve_link_code(value: Any) -> Optional[str]:
    """Counterpart to `_resolve_link_id` — extracts the linked record's `code`
    (the LTAR display value) so callers can filter by it. NocoDB v2 LTAR
    filters compare against the display value, not the id."""
    if value is None or value == "":
        return None
    if isinstance(value, list):
        if not value:
            return None
        first = value[0]
        if isinstance(first, dict):
            code = first.get("code")
            return str(code) if code else None
        return None
    if isinstance(value, dict):
        code = value.get("code")
        return str(code) if code else None
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
