"""Generic value-table client.

`set_exp_params`, `set_exp_features`, and `set_exp_attributes` share the
same `(experiment, code, dim, value)` shape — one parameterised class
serves all three. The differing FK-code column name (`param` / `feature` /
`attribute`) is passed at construction.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Mapping, Optional

from ._base import _BaseTableClient
from ._codes import make_value_code
from .schema import ParamColumns

if TYPE_CHECKING:
    from .dim_positions import DimPositionsClient


@dataclass(frozen=True)
class ValueRow:
    """One row from a `set_exp_*` table."""

    id: int
    code: str
    experiment_id: int
    fk_code: str  # the param/feature/attribute code this row references
    dim_id: Optional[int]
    value: Any  # str for params, float for features/attributes


@dataclass(frozen=True)
class ValueWriteItem:
    """Single value to write — used by `write_batch`."""

    value_code: str
    value: Any
    domain: Optional[str] = None
    axes: Optional[Mapping[str, int]] = None


class ValueClient(_BaseTableClient):
    """Generic CRUD for `set_exp_params` / `set_exp_features` / `set_exp_attributes`.

    Parameterised by the target table's id and the FK-code column name
    (`param` / `feature` / `attribute`). Reuses a shared `DimPositionsClient`
    so its in-process cache benefits every write.
    """

    # The shared columns (id/code/experiment/dim/value) live on `ParamColumns`
    # but are identical across all three tables — using `ParamColumns.*` here
    # is a safe shorthand.

    def __init__(
        self,
        http,
        base_id: str,
        table_id: str,
        *,
        fk_code_column: str,
        dim_client: "DimPositionsClient",
        link_field_ids: dict[str, str] | None = None,
    ):
        super().__init__(http, base_id, table_id, link_field_ids=link_field_ids)
        self._fk_col = fk_code_column
        self._dim_client = dim_client

    # ─── Write ────────────────────────────────────────────────────────

    def write(
        self,
        *,
        exp_id: int,
        exp_code: str,
        value_code: str,
        value: Any,
        domain: Optional[str] = None,
        axes: Optional[Mapping[str, int]] = None,
    ) -> ValueRow:
        """Write a single value.

        If `axes` is provided, `domain` must also be provided; the
        corresponding `dim_position` is upserted via the shared
        `DimPositionsClient`. If `axes` is `None`, the row's `dim` link
        stays null (per-experiment scope).
        """
        dim_id, dim_code = self._resolve_dim(domain=domain, axes=axes)
        row_code = make_value_code(exp_code=exp_code, value_code=value_code, dim_code=dim_code)
        body = self._build_body(
            row_code=row_code,
            value_code=value_code,
            value=value,
        )
        # 1. Create the row without LTAR fields (NocoDB v2 silently drops
        #    inline link values, especially in bulk POSTs).
        self._http.records_create(self._table_id, body)
        # 2. Re-fetch by code to get the new row's id (POST response may be partial).
        row = self._lookup_by_code(row_code)
        record_id = int(row[ParamColumns.ID])
        # 3. Wire links via the dedicated /links/ endpoint.
        self._link(ParamColumns.EXPERIMENT, record_id, exp_id)
        if dim_id is not None:
            self._link(ParamColumns.DIM, record_id, dim_id)
        return self._row_to_value(self._lookup_by_code(row_code))

    def write_batch(
        self,
        *,
        exp_id: int,
        exp_code: str,
        items: list[ValueWriteItem],
    ) -> list[ValueRow]:
        """Bulk-create rows, then wire LTAR links via the /links/ endpoint.

        NocoDB v2's bulk records-create silently drops link-field values
        from the body, so we keep `experiment` and `dim` out of the bulk
        POST and wire them afterwards via the dedicated /links/ endpoint.
        Cost: 1 bulk records-create + 2N link calls per batch — but the
        link columns reliably populate, regardless of single vs bulk.
        """
        if not items:
            return []
        # Resolve dims (cached) and build value-only bodies for the bulk POST.
        bodies: list[dict[str, Any]] = []
        per_row_dim_ids: list[Optional[int]] = []
        row_codes: list[str] = []
        for item in items:
            dim_id, dim_code = self._resolve_dim(domain=item.domain, axes=item.axes)
            row_code = make_value_code(
                exp_code=exp_code, value_code=item.value_code, dim_code=dim_code,
            )
            bodies.append(
                self._build_body(
                    row_code=row_code,
                    value_code=item.value_code,
                    value=item.value,
                )
            )
            per_row_dim_ids.append(dim_id)
            row_codes.append(row_code)

        # 1. Bulk-create. Response shape varies; we re-fetch by code below.
        self._http.records_create(self._table_id, bodies)

        # 2. Re-fetch each row to get its assigned id, then set the LTAR links.
        results: list[ValueRow] = []
        for row_code, dim_id in zip(row_codes, per_row_dim_ids):
            row = self._lookup_by_code(row_code)
            record_id = int(row[ParamColumns.ID])
            self._link(ParamColumns.EXPERIMENT, record_id, exp_id)
            if dim_id is not None:
                self._link(ParamColumns.DIM, record_id, dim_id)
            results.append(self._row_to_value(self._lookup_by_code(row_code)))
        return results

    # ─── Read ─────────────────────────────────────────────────────────

    def read(
        self,
        *,
        exp_id: int,
        value_code: Optional[str] = None,
    ) -> list[ValueRow]:
        """Read every row for an experiment, optionally filtered by FK code."""
        clauses = [f"({ParamColumns.EXPERIMENT},eq,{exp_id})"]
        if value_code is not None:
            clauses.append(f"({self._fk_col},eq,{value_code})")
        rows = self._http.records_list(self._table_id, where="~and".join(clauses))
        return [self._row_to_value(r) for r in rows]

    def read_static(self, exp_id: int) -> dict[str, Any]:
        """Every value where `dim IS NULL`, returned as `{value_code: value}`.

        Useful for `set_exp_params` to retrieve per-experiment static values
        before a fab run.
        """
        rows = self._http.records_list(
            self._table_id,
            where=(
                f"({ParamColumns.EXPERIMENT},eq,{exp_id})"
                f"~and({ParamColumns.DIM},is,null)"
            ),
        )
        return {str(r[self._fk_col]): r[ParamColumns.VALUE] for r in rows if self._fk_col in r}

    def read_trajectory(
        self,
        exp_id: int,
    ) -> dict[str, list[tuple[dict[str, int], Any]]]:
        """Every value where `dim IS NOT NULL`, grouped by code.

        Returns `{value_code: [(axes, value), ...]}`. For `set_exp_params`,
        useful for retrieving per-layer trajectories.
        """
        rows = self._http.records_list(
            self._table_id,
            where=(
                f"({ParamColumns.EXPERIMENT},eq,{exp_id})"
                f"~and({ParamColumns.DIM},isnot,null)"
            ),
        )
        out: dict[str, list[tuple[dict[str, int], Any]]] = {}
        for r in rows:
            code = str(r.get(self._fk_col, ""))
            if not code:
                continue
            dim_id = self._extract_dim_id(r.get(ParamColumns.DIM))
            if dim_id is None:
                continue
            position = self._dim_client.get(dim_id)
            out.setdefault(code, []).append((dict(position.axes), r[ParamColumns.VALUE]))
        return out

    # ─── Internal ──────────────────────────────────────────────────────

    def _resolve_dim(
        self,
        *,
        domain: Optional[str],
        axes: Optional[Mapping[str, int]],
    ) -> tuple[Optional[int], Optional[str]]:
        """Resolve (domain, axes) to (dim_id, dim_code). Both None for static scope."""
        if axes is None:
            return None, None
        if domain is None:
            raise ValueError("`domain` is required when `axes` is provided")
        position = self._dim_client.get_or_create(domain=domain, axes=axes)
        return position.id, position.code

    def _build_body(
        self,
        *,
        row_code: str,
        value_code: str,
        value: Any,
    ) -> dict[str, Any]:
        """Build a records-create body with non-LTAR columns only.

        ``experiment`` and ``dim`` are LTAR fields and are wired post-create
        via the /links/ endpoint, not via inline POST values.
        """
        return {
            ParamColumns.CODE: row_code,
            self._fk_col: value_code,
            ParamColumns.VALUE: value,
        }

    def _lookup_by_code(self, row_code: str) -> dict[str, Any]:
        rows = self._http.records_list(
            self._table_id,
            where=f"({ParamColumns.CODE},eq,{row_code})",
            limit=1,
        )
        if not rows:
            raise RuntimeError(f"Value row with code={row_code!r} not found after insert")
        return rows[0]

    def _row_to_value(self, row: dict[str, Any]) -> ValueRow:
        return ValueRow(
            id=int(row[ParamColumns.ID]),
            code=str(row[ParamColumns.CODE]),
            experiment_id=self._extract_link_id(row.get(ParamColumns.EXPERIMENT)) or 0,
            fk_code=str(row.get(self._fk_col, "")),
            dim_id=self._extract_dim_id(row.get(ParamColumns.DIM)),
            value=row.get(ParamColumns.VALUE),
        )

    @staticmethod
    def _extract_link_id(value: Any) -> Optional[int]:
        if value is None or value == "":
            return None
        if isinstance(value, list):
            if not value:
                return None
            first = value[0]
            return int(first.get("Id", 0)) if isinstance(first, dict) else int(first)
        if isinstance(value, dict):
            return int(value.get("Id", 0)) or None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _extract_dim_id(value: Any) -> Optional[int]:
        return ValueClient._extract_link_id(value)
