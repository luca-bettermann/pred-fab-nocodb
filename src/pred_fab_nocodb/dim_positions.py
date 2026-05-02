"""dim_positions table client.

Manages the catalogue of (domain, axes-tuple) coordinates that feature,
attribute, and trajectory-parameter values are positioned at. Codes are
auto-generated as `'{domain}.d{depth}.{count}'` with the counter scoped
per (domain, depth).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from ._axes import canonicalize_axes
from ._base import _BaseTableClient
from ._codes import make_dim_position_code
from .errors import NotFoundError
from .schema import DimPositionColumns


@dataclass(frozen=True)
class DimPosition:
    """One row from the `dim_positions` table."""

    id: int
    code: str
    domain: str
    depth: int
    axes: dict[str, int]


class DimPositionsClient(_BaseTableClient):
    """Read/write the `dim_positions` table.

    Maintains an in-process cache keyed by (domain, canonical_axes) so that
    repeated references to the same position within a write batch do not
    incur additional round-trips.
    """

    def __init__(self, http, base_id: str, table_id: str):
        super().__init__(http, base_id, table_id)
        self._cache: dict[tuple[str, str], DimPosition] = {}

    # ─── Read ─────────────────────────────────────────────────────────

    def get(self, position_id: int) -> DimPosition:
        """Fetch a position by NocoDB id."""
        row = self._http.records_get(self._table_id, position_id)
        return _row_to_position(row)

    def get_by_code(self, code: str) -> DimPosition:
        """Fetch a position by its generated code."""
        rows = self._http.records_list(
            self._table_id,
            where=f"({DimPositionColumns.CODE},eq,{code})",
            limit=1,
        )
        if not rows:
            raise NotFoundError(f"DimPosition with code={code!r} not found")
        return _row_to_position(rows[0])

    def find(self, *, domain: str, axes: Mapping[str, int]) -> DimPosition | None:
        """Look up a position by (domain, axes). Returns `None` if absent.

        Uses the in-process cache when available.
        """
        canonical = canonicalize_axes(axes)
        cached = self._cache.get((domain, canonical))
        if cached is not None:
            return cached
        rows = self._http.records_list(
            self._table_id,
            where=(
                f"({DimPositionColumns.DOMAIN},eq,{domain})"
                f"~and({DimPositionColumns.AXES},eq,{canonical})"
            ),
            limit=1,
        )
        if not rows:
            return None
        position = _row_to_position(rows[0])
        self._cache[(domain, canonical)] = position
        return position

    def list_by_domain(
        self,
        *,
        domain: str,
        depth: int | None = None,
    ) -> list[DimPosition]:
        """All positions in `domain`, optionally filtered by `depth`."""
        clauses = [f"({DimPositionColumns.DOMAIN},eq,{domain})"]
        if depth is not None:
            clauses.append(f"({DimPositionColumns.DEPTH},eq,{depth})")
        rows = self._http.records_list(self._table_id, where="~and".join(clauses))
        return [_row_to_position(r) for r in rows]

    # ─── Write ────────────────────────────────────────────────────────

    def get_or_create(
        self,
        *,
        domain: str,
        axes: Mapping[str, int],
    ) -> DimPosition:
        """Idempotent. Returns existing position if `(domain, axes)` matches,
        otherwise creates a new one with code `'{domain}.d{depth}.{count}'`.
        """
        existing = self.find(domain=domain, axes=axes)
        if existing is not None:
            return existing

        depth = len(axes)
        canonical = canonicalize_axes(axes)
        count = self._count_in_domain_depth(domain=domain, depth=depth)
        code = make_dim_position_code(domain, depth, count)

        body: dict[str, Any] = {
            DimPositionColumns.CODE: code,
            DimPositionColumns.DOMAIN: domain,
            DimPositionColumns.DEPTH: depth,
            DimPositionColumns.AXES: canonical,
        }
        result = self._http.records_create(self._table_id, body)
        position = (
            _row_to_position(result)
            if isinstance(result, dict) and DimPositionColumns.ID in result
            else self.get_by_code(code)
        )
        self._cache[(domain, canonical)] = position
        return position

    def get_or_create_batch(
        self,
        *,
        domain: str,
        axes_list: list[Mapping[str, int]],
    ) -> list[DimPosition]:
        """Bulk version of `get_or_create`. Reuses the cache."""
        return [self.get_or_create(domain=domain, axes=axes) for axes in axes_list]

    # ─── Internal ──────────────────────────────────────────────────────

    def _count_in_domain_depth(self, *, domain: str, depth: int) -> int:
        """Count rows currently at this `(domain, depth)`. Used for code generation."""
        return self._http.records_count(
            self._table_id,
            where=(
                f"({DimPositionColumns.DOMAIN},eq,{domain})"
                f"~and({DimPositionColumns.DEPTH},eq,{depth})"
            ),
        )


def _row_to_position(row: dict[str, Any]) -> DimPosition:
    axes_raw = row.get(DimPositionColumns.AXES, "{}")
    if isinstance(axes_raw, str):
        try:
            axes = json.loads(axes_raw) if axes_raw else {}
        except json.JSONDecodeError:
            axes = {}
    elif isinstance(axes_raw, dict):
        axes = axes_raw
    else:
        axes = {}
    return DimPosition(
        id=int(row[DimPositionColumns.ID]),
        code=str(row[DimPositionColumns.CODE]),
        domain=str(row.get(DimPositionColumns.DOMAIN, "")),
        depth=int(row.get(DimPositionColumns.DEPTH, 0)),
        axes={str(k): int(v) for k, v in axes.items()},
    )
