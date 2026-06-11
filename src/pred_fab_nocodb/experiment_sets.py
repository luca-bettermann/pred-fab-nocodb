"""ExperimentSets table client — named experiment groups (discovery / exploration / test runs).

Supersedes the old `datasets` table. One row per group; membership is a JSON list in the
`members` column (a denormalised many-to-many that mirrors pred-fab's `ExperimentSet.to_dict`
1:1), so this is a link-free table client. See the KB note *ExperimentSet data model refactor*.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from ._base import _BaseTableClient
from .errors import NotFoundError
from .schema import ExperimentSetColumns


@dataclass(frozen=True)
class ExperimentSet:
    """One row from the `experiment_sets` table."""

    id: int
    code: str
    strategy: str
    ordered: bool = False
    parent: Optional[str] = None            # parent set's code
    members: list[str] = field(default_factory=list)


class ExperimentSetsClient(_BaseTableClient):
    """Read/write the `experiment_sets` table (link-free; members stored as JSON)."""

    def get_by_code(self, code: str) -> ExperimentSet:
        rows = self._http.records_list(
            self._table_id,
            where=f"({ExperimentSetColumns.CODE},eq,{code})",
            limit=1,
        )
        if not rows:
            raise NotFoundError(f"ExperimentSet with code={code!r} not found")
        return _row_to_set(rows[0])

    def list_all(self) -> list[ExperimentSet]:
        """Every group (used by ``pull_experiment_sets``)."""
        return [_row_to_set(r) for r in self._http.records_list(self._table_id)]

    def upsert(
        self,
        *,
        code: str,
        strategy: str,
        ordered: bool = False,
        parent: Optional[str] = None,
        members: Optional[list[str]] = None,
    ) -> ExperimentSet:
        """Create or update a group row, keyed by ``code`` (members serialized to JSON)."""
        body: dict[str, Any] = {
            ExperimentSetColumns.CODE: code,
            ExperimentSetColumns.STRATEGY: strategy,
            ExperimentSetColumns.ORDERED: bool(ordered),
            ExperimentSetColumns.MEMBERS: json.dumps(list(members or [])),
            ExperimentSetColumns.PARENT: parent,
        }
        try:
            existing = self.get_by_code(code)
        except NotFoundError:
            existing = None

        if existing is None:
            self._http.records_create(self._table_id, body)
        else:
            self._http.records_update(self._table_id, {ExperimentSetColumns.ID: existing.id, **body})
        return self.get_by_code(code)


def _row_to_set(row: dict[str, Any]) -> ExperimentSet:
    members = row.get(ExperimentSetColumns.MEMBERS)
    if isinstance(members, str):
        try:
            members = json.loads(members)
        except (json.JSONDecodeError, TypeError):
            members = []
    if not isinstance(members, list):
        members = []
    return ExperimentSet(
        id=int(row[ExperimentSetColumns.ID]),
        code=str(row[ExperimentSetColumns.CODE]),
        strategy=str(row.get(ExperimentSetColumns.STRATEGY, "")),
        ordered=bool(row.get(ExperimentSetColumns.ORDERED, False)),
        parent=row.get(ExperimentSetColumns.PARENT) or None,
        members=[str(m) for m in members],
    )
