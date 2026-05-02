"""dim_positions table client.

Manages the catalogue of (domain, axes-tuple) coordinates that feature, attribute,
and trajectory-parameter values are positioned at. Codes are auto-generated
as `'{domain}.d{depth}.{count}'` with the counter scoped per (domain, depth).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from ._base import _BaseTableClient


@dataclass(frozen=True)
class DimPosition:
    """One row from the `dim_positions` table."""

    id: int
    code: str  # e.g. "structural:nodes.d2.42"
    domain: str  # e.g. "structural:nodes"
    depth: int
    axes: dict[str, int]


class DimPositionsClient(_BaseTableClient):
    """Read/write the `dim_positions` table.

    Maintains an in-process cache keyed by (domain, canonical_axes) so that
    repeated references to the same position within a write batch do not
    incur additional round-trips.
    """

    def __init__(self, http, base_id: str):
        super().__init__(http, base_id)
        self._cache: dict[tuple[str, str], DimPosition] = {}

    # ─── Read ─────────────────────────────────────────────────────────

    def get(self, position_id: int) -> DimPosition:
        """Fetch a position by NocoDB id."""
        raise NotImplementedError

    def get_by_code(self, code: str) -> DimPosition:
        """Fetch a position by its generated code."""
        raise NotImplementedError

    def find(self, *, domain: str, axes: Mapping[str, int]) -> DimPosition | None:
        """Look up a position by (domain, axes). Returns `None` if absent."""
        raise NotImplementedError

    def list_by_domain(
        self,
        *,
        domain: str,
        depth: int | None = None,
    ) -> list[DimPosition]:
        """All positions in `domain`, optionally filtered by `depth`."""
        raise NotImplementedError

    # ─── Write ────────────────────────────────────────────────────────

    def get_or_create(
        self,
        *,
        domain: str,
        axes: Mapping[str, int],
    ) -> DimPosition:
        """Idempotent. Returns the existing position if `(domain, axes)` matches,
        otherwise creates a new one with code `'{domain}.d{depth}.{count}'` where
        `count` is the current row count at this `(domain, depth)`.

        Cached in-process; safe to call repeatedly with the same arguments.
        """
        raise NotImplementedError

    def get_or_create_batch(
        self,
        *,
        domain: str,
        axes_list: list[Mapping[str, int]],
    ) -> list[DimPosition]:
        """Bulk version of `get_or_create` — single fetch + one create-many call."""
        raise NotImplementedError

    # ─── Internal ──────────────────────────────────────────────────────

    def _next_code(self, domain: str, depth: int) -> str:
        """Compute the next counter code for `(domain, depth)`.

        Counter = number of rows currently at this `(domain, depth)`. Race-safe
        under sequential writers; under concurrent writers, the database's
        UNIQUE(code) rejects duplicates and the writer retries with the next count.
        """
        raise NotImplementedError
