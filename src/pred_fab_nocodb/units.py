"""`units` table client — this rig's hardware units (printer, scanner, …).

One row per unit, keyed by ``role``. ``sensors`` links the unit's sensor `services`.
Per-rig hardware param *values* (home_joints, tool_offset, …) live in `params`, not here —
a unit row is the hardware identity + its sensors. Upsert re-asserts the ``sensors`` links
idempotently (additive)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from ._base import _BaseTableClient
from ._rows import _resolve_link_displays, _resolve_link_ids
from .errors import NotFoundError
from .schema import ServiceColumns, UnitColumns


@dataclass(frozen=True)
class Unit:
    """One row from the `units` table."""

    id: int
    role: str
    robot: Optional[str] = None
    tool: Optional[str] = None
    sensors: list[str] = field(default_factory=list)        # sensor service names
    sensor_ids: list[int] = field(default_factory=list)     # sensor service ids


class UnitsClient(_BaseTableClient):
    """Read/write the `units` table."""

    def get_by_role(self, role: str) -> Unit:
        rows = self._http.records_list(
            self._table_id, where=f"({UnitColumns.ROLE},eq,{role})", limit=1,
        )
        if not rows:
            raise NotFoundError(f"Unit with role={role!r} not found")
        return _row_to_unit(rows[0])

    def list_all(self) -> list[Unit]:
        return [_row_to_unit(r) for r in self._http.records_list(self._table_id)]

    def read(self) -> dict[str, Unit]:
        """Whole table keyed by ``role``."""
        return {u.role: u for u in self.list_all()}

    def upsert(
        self,
        *,
        role: str,
        robot: Optional[str] = None,
        tool: Optional[str] = None,
        sensor_ids: Optional[list[int]] = None,
    ) -> Unit:
        """Create or update a unit row, keyed by ``role``; re-assert its ``sensors`` links.

        ``sensor_ids`` are resolved service ids (the caller maps sensor names → ids)."""
        body: dict[str, Any] = {
            UnitColumns.ROLE: role,
            UnitColumns.ROBOT: robot,
            UnitColumns.TOOL: tool,
        }
        try:
            existing: Optional[Unit] = self.get_by_role(role)
        except NotFoundError:
            existing = None

        if existing is None:
            self._http.records_create(self._table_id, body)
        else:
            self._http.records_update(self._table_id, {UnitColumns.ID: existing.id, **body})
        unit = self.get_by_role(role)
        if sensor_ids:
            self._link(UnitColumns.SENSORS, unit.id, sensor_ids)
            unit = self.get_by_role(role)
        return unit


def _row_to_unit(row: dict[str, Any]) -> Unit:
    return Unit(
        id=int(row[UnitColumns.ID]),
        role=str(row[UnitColumns.ROLE]),
        robot=row.get(UnitColumns.ROBOT) or None,
        tool=row.get(UnitColumns.TOOL) or None,
        sensors=_resolve_link_displays(row.get(UnitColumns.SENSORS), ServiceColumns.NAME),
        sensor_ids=_resolve_link_ids(row.get(UnitColumns.SENSORS)),
    )
