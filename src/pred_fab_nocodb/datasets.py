"""Datasets table client.

Datasets are named groups of experiments within a study. Two orthogonal
attributes:

- **strategy** — *how* experiments are generated (grid, baseline, exploration, inference)
- **purpose** — *what* they're used for (reference, train, validation, test)

1:M with experiments via the `experiments.dataset` FK.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from ._base import _BaseTableClient
from ._codes import make_dataset_code
from .errors import NotFoundError
from .experiments import _resolve_link_id
from .schema import DatasetColumns, Purpose, Strategy


@dataclass(frozen=True)
class Dataset:
    """One row from the `datasets` table."""

    id: int
    code: str
    study_id: int
    name: str
    strategy: Strategy
    purpose: Purpose
    description: Optional[str] = None


class DatasetsClient(_BaseTableClient):
    """Read/write the `datasets` table."""

    def get_by_code(self, code: str) -> Dataset:
        """Fetch a dataset by its full code (e.g. `'ADVEI_2026/baseline'`)."""
        rows = self._http.records_list(
            self._table_id,
            where=f"({DatasetColumns.CODE},eq,{code})",
            limit=1,
        )
        if not rows:
            raise NotFoundError(f"Dataset with code={code!r} not found")
        return _row_to_dataset(rows[0])

    def list_by_study(self, study_id: int) -> list[Dataset]:
        """List every dataset belonging to a study."""
        rows = self._http.records_list(
            self._table_id,
            where=f"({DatasetColumns.STUDY},eq,{study_id})",
        )
        return [_row_to_dataset(r) for r in rows]

    def create(
        self,
        *,
        study_id: int,
        study_code: str,
        name: str,
        strategy: Strategy,
        purpose: Purpose,
        description: Optional[str] = None,
    ) -> Dataset:
        """Create a new dataset row.

        `study_code` is required for code generation; `study_id` is the FK target.
        """
        code = make_dataset_code(study_code, name)
        body: dict[str, Any] = {
            DatasetColumns.CODE: code,
            DatasetColumns.STUDY: study_id,
            DatasetColumns.NAME: name,
            DatasetColumns.STRATEGY: strategy.value,
            DatasetColumns.PURPOSE: purpose.value,
        }
        if description is not None:
            body[DatasetColumns.DESCRIPTION] = description
        self._http.records_create(self._table_id, body)
        # NocoDB v2's POST response sometimes contains only {"Id": N} rather
        # than the full row — re-fetch by the just-written code to get a
        # complete Dataset reliably.
        return self.get_by_code(code)


def _row_to_dataset(row: dict[str, Any]) -> Dataset:
    study_id = _resolve_link_id(row.get(DatasetColumns.STUDY)) or 0
    return Dataset(
        id=int(row[DatasetColumns.ID]),
        code=str(row[DatasetColumns.CODE]),
        study_id=study_id,
        name=str(row.get(DatasetColumns.NAME, "")),
        strategy=Strategy(row.get(DatasetColumns.STRATEGY, Strategy.BASELINE.value)),
        purpose=Purpose(row.get(DatasetColumns.PURPOSE, Purpose.TRAIN.value)),
        description=row.get(DatasetColumns.DESCRIPTION),
    )
