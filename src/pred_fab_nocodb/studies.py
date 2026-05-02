"""Studies table client."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from ._base import _BaseTableClient
from .errors import NotFoundError
from .schema import StudyColumns


@dataclass(frozen=True)
class Study:
    """One row from the `studies` table."""

    id: int
    code: str
    description: Optional[str] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None


class StudiesClient(_BaseTableClient):
    """Read/write the `studies` table."""

    def get_by_code(self, code: str) -> Study:
        """Fetch a study by its code (e.g. `'ADVEI_2026'`). Raises `NotFoundError` if absent."""
        rows = self._http.records_list(
            self._table_id,
            where=f"({StudyColumns.CODE},eq,{code})",
            limit=1,
        )
        if not rows:
            raise NotFoundError(f"Study with code={code!r} not found")
        return _row_to_study(rows[0])

    def list_all(self) -> list[Study]:
        """Return every study in the workspace."""
        rows = self._http.records_list(self._table_id)
        return [_row_to_study(r) for r in rows]

    def create(
        self,
        *,
        code: str,
        description: Optional[str] = None,
    ) -> Study:
        """Create a new study row."""
        body: dict[str, Any] = {StudyColumns.CODE: code}
        if description is not None:
            body[StudyColumns.DESCRIPTION] = description
        result = self._http.records_create(self._table_id, body)
        # NocoDB's POST returns the created row including its assigned Id
        return self.get_by_code(code) if not isinstance(result, dict) else _row_to_study(result)


def _row_to_study(row: dict[str, Any]) -> Study:
    return Study(
        id=int(row[StudyColumns.ID]),
        code=str(row[StudyColumns.CODE]),
        description=row.get(StudyColumns.DESCRIPTION),
        started_at=_parse_dt(row.get(StudyColumns.STARTED_AT)),
        ended_at=_parse_dt(row.get(StudyColumns.ENDED_AT)),
    )


def _parse_dt(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
