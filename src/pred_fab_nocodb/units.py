"""`units` table client — rig assemblies (printer, scanner, …) composed of hardware devices.

One row per unit, keyed by ``role``. ``robot``/``tool`` are single `hardware` links and
``sensors`` an m2m `hardware` link — a unit is a named assembly of devices; the devices carry
their physics as linked `params`. Upsert re-asserts the links idempotently."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from ._base import _BaseTableClient
from ._rows import _resolve_link_display, _resolve_link_displays, _resolve_link_id, _resolve_link_ids
from .errors import NotFoundError
from .schema import HardwareColumns, UnitColumns


@dataclass(frozen=True)
class Unit:
    """One row from the `units` table — a rig assembly of hardware devices."""

    id: int
    role: str
    robot: Optional[str] = None          # robot device name
    robot_id: Optional[int] = None
    tool: Optional[str] = None           # tool device name
    tool_id: Optional[int] = None
    sensors: list[str] = field(default_factory=list)        # sensor device names
    sensor_ids: list[int] = field(default_factory=list)     # sensor device ids


class UnitsClient(_BaseTableClient):
    """Read/write the `units` table (robot/tool/sensors are `hardware` links)."""

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
        robot_id: Optional[int] = None,
        tool_id: Optional[int] = None,
        sensor_ids: Optional[list[int]] = None,
    ) -> Unit:
        """Create or update a unit row, keyed by ``role``; re-assert its `hardware` links.

        ``robot_id``/``tool_id``/``sensor_ids`` are resolved `hardware` device ids (the caller
        maps device names → ids)."""
        body: dict[str, Any] = {UnitColumns.ROLE: role}
        try:
            existing: Optional[Unit] = self.get_by_role(role)
        except NotFoundError:
            existing = None

        if existing is None:
            self._http.records_create(self._table_id, body)
        else:
            self._http.records_update(self._table_id, {UnitColumns.ID: existing.id, **body})
        unit = self.get_by_role(role)
        if robot_id is not None:
            self._link(UnitColumns.ROBOT, unit.id, robot_id)
        if tool_id is not None:
            self._link(UnitColumns.TOOL, unit.id, tool_id)
        if sensor_ids:
            self._link(UnitColumns.SENSORS, unit.id, sensor_ids)
        if robot_id is not None or tool_id is not None or sensor_ids:
            unit = self.get_by_role(role)
        return unit


def _row_to_unit(row: dict[str, Any]) -> Unit:
    return Unit(
        id=int(row[UnitColumns.ID]),
        role=str(row[UnitColumns.ROLE]),
        robot=_resolve_link_display(row.get(UnitColumns.ROBOT), HardwareColumns.NAME),
        robot_id=_resolve_link_id(row.get(UnitColumns.ROBOT)),
        tool=_resolve_link_display(row.get(UnitColumns.TOOL), HardwareColumns.NAME),
        tool_id=_resolve_link_id(row.get(UnitColumns.TOOL)),
        sensors=_resolve_link_displays(row.get(UnitColumns.SENSORS), HardwareColumns.NAME),
        sensor_ids=_resolve_link_ids(row.get(UnitColumns.SENSORS)),
    )
