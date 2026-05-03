"""set_study_constants table client."""
from __future__ import annotations

from typing import Any, Optional

from ._base import _BaseTableClient
from ._codes import make_study_constant_code
from .errors import NotFoundError
from .schema import StudyConstantColumns


class StudyConstantsClient(_BaseTableClient):
    """Read/write per-study constants.

    Constants are study-level parameters that don't vary across experiments
    (material density, supply voltage, conversion ratios, etc.). The column
    holding the constant's identifying code is `param`.
    """

    def read(self, study_id: int) -> dict[str, float]:
        """Return all constants for a study as `{param_code: value}`."""
        rows = self._http.records_list(
            self._table_id,
            where=f"({StudyConstantColumns.STUDY},eq,{study_id})",
        )
        return {
            str(r[StudyConstantColumns.PARAM]): float(r[StudyConstantColumns.VALUE])
            for r in rows
            if StudyConstantColumns.PARAM in r and StudyConstantColumns.VALUE in r
        }

    def get(self, *, study_id: int, param_code: str) -> Optional[float]:
        """Get a single constant value, or `None` if absent."""
        rows = self._http.records_list(
            self._table_id,
            where=(
                f"({StudyConstantColumns.STUDY},eq,{study_id})"
                f"~and({StudyConstantColumns.PARAM},eq,{param_code})"
            ),
            limit=1,
        )
        if not rows:
            return None
        return float(rows[0][StudyConstantColumns.VALUE])

    def write(
        self,
        *,
        study_id: int,
        study_code: str,
        param_code: str,
        value: float,
    ) -> None:
        """Create or update a constant value.

        `study_code` is required for code generation; `study_id` is the FK target.
        """
        code = make_study_constant_code(study_code, param_code)
        existing = self._find_id(study_id=study_id, param_code=param_code)
        body: dict[str, Any] = {
            StudyConstantColumns.CODE: code,
            StudyConstantColumns.PARAM: param_code,
            StudyConstantColumns.VALUE: value,
        }
        if existing is None:
            self._http.records_create(self._table_id, body)
            # Look up the new row by its just-written `code` (the study link
            # isn't set yet, so we can't filter by study_id).
            constant_id = self._find_id_by_code(code)
            if constant_id is not None:
                self._link(StudyConstantColumns.STUDY, constant_id, study_id)
        else:
            body[StudyConstantColumns.ID] = existing
            self._http.records_update(self._table_id, body)
            # Existing row already has its study link set; nothing to do.

    def delete(self, *, study_id: int, param_code: str) -> None:
        """Remove a constant. Raises `NotFoundError` if it doesn't exist."""
        existing = self._find_id(study_id=study_id, param_code=param_code)
        if existing is None:
            raise NotFoundError(
                f"Constant {param_code!r} not found in study_id={study_id}"
            )
        self._http.records_delete(self._table_id, {StudyConstantColumns.ID: existing})

    def _find_id(self, *, study_id: int, param_code: str) -> Optional[int]:
        rows = self._http.records_list(
            self._table_id,
            where=(
                f"({StudyConstantColumns.STUDY},eq,{study_id})"
                f"~and({StudyConstantColumns.PARAM},eq,{param_code})"
            ),
            limit=1,
        )
        if not rows:
            return None
        return int(rows[0][StudyConstantColumns.ID])

    def _find_id_by_code(self, code: str) -> Optional[int]:
        """Lookup by `code` only — used right after create() before the study
        link is set, when filter-by-study_id wouldn't match yet."""
        rows = self._http.records_list(
            self._table_id,
            where=f"({StudyConstantColumns.CODE},eq,{code})",
            limit=1,
        )
        if not rows:
            return None
        return int(rows[0][StudyConstantColumns.ID])
