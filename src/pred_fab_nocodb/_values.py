"""Generic value-table client.

`set_exp_params`, `set_exp_features`, and `set_exp_attributes` share the
same `(experiment, code, dim, value)` shape — one parameterised class
serves all three. The differing FK-code column name (`param` / `feature` /
`attribute`) is passed at construction.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Mapping

from ._base import _BaseTableClient

if TYPE_CHECKING:
    from .dim_positions import DimPositionsClient


@dataclass(frozen=True)
class ValueRow:
    """One row from a `set_exp_*` table."""

    id: int
    code: str
    experiment_id: int
    fk_code: str  # the param/feature/attribute code this row references
    dim_id: int | None
    value: Any  # str for params, float for features/attributes


@dataclass(frozen=True)
class ValueWriteItem:
    """Single value to write — used by `write_batch`."""

    value_code: str  # the param/feature/attribute code
    value: Any
    domain: str | None = None  # required if axes is non-None
    axes: Mapping[str, int] | None = None  # None ↔ per-experiment scope (no dim)


class ValueClient(_BaseTableClient):
    """Generic CRUD for `set_exp_params` / `set_exp_features` / `set_exp_attributes`.

    Parameters
    ----------
    table:
        NocoDB table name (one of `Tables.SET_EXP_*`).
    fk_code_column:
        Column name holding the foreign code (e.g. `"param"`, `"feature"`,
        `"attribute"`). Differs per table.
    dim_client:
        Shared `DimPositionsClient` — reused across all three value clients
        so the dim_position cache benefits every write.
    """

    def __init__(
        self,
        http,
        base_id: str,
        *,
        table: str,
        fk_code_column: str,
        dim_client: "DimPositionsClient",
    ):
        super().__init__(http, base_id)
        self._table = table
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
        domain: str | None = None,
        axes: Mapping[str, int] | None = None,
    ) -> ValueRow:
        """Write a single value.

        If `axes` is provided, `domain` must also be provided; the
        corresponding `dim_position` is upserted via the shared
        `DimPositionsClient`. If `axes` is `None`, the row's `dim` link
        stays null (per-experiment scope).

        `exp_code` is required for code generation; `exp_id` is the FK target.
        """
        raise NotImplementedError

    def write_batch(
        self,
        *,
        exp_id: int,
        exp_code: str,
        items: list[ValueWriteItem],
    ) -> list[ValueRow]:
        """Bulk write. Reuses dim_position lookups via the shared cache."""
        raise NotImplementedError

    # ─── Read ─────────────────────────────────────────────────────────

    def read(
        self,
        *,
        exp_id: int,
        value_code: str | None = None,
    ) -> list[ValueRow]:
        """Read every row for an experiment, optionally filtered by FK code."""
        raise NotImplementedError

    def read_static(self, exp_id: int) -> dict[str, Any]:
        """Convenience: every value where `dim IS NULL`, returned as `{value_code: value}`.

        Useful for `set_exp_params` to retrieve per-experiment static values
        before a fab run.
        """
        raise NotImplementedError

    def read_trajectory(
        self,
        exp_id: int,
    ) -> dict[str, list[tuple[dict[str, int], Any]]]:
        """Convenience: every value where `dim IS NOT NULL`, grouped by code.

        Returns `{value_code: [(axes, value), ...]}`. Useful for
        `set_exp_params` to retrieve per-layer trajectories.
        """
        raise NotImplementedError
