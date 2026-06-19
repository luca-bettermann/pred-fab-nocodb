"""`hardware` table client — physical device identity (robots, tools, sensors).

One row per physical device, keyed by ``name``; *identity only* (name/type/kind). A device's
variable physics live as `params` rows linked to it; this table is the link-target + the
former ``robots`` registry. Units reference their devices here; a sensor service points to its
device via ``services.hardware``."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from ._base import _BaseTableClient
from .errors import NotFoundError
from .schema import HardwareColumns, HardwareType


@dataclass(frozen=True)
class Hardware:
    """One row from the `hardware` table."""

    id: int
    name: str
    type: HardwareType
    kind: Optional[str] = None


class HardwareClient(_BaseTableClient):
    """Read/write the `hardware` table (device identity; link-free)."""

    def get_by_name(self, name: str) -> Hardware:
        rows = self._http.records_list(
            self._table_id, where=f"({HardwareColumns.NAME},eq,{name})", limit=1,
        )
        if not rows:
            raise NotFoundError(f"Hardware with name={name!r} not found")
        return _row_to_hardware(rows[0])

    def list_all(self) -> list[Hardware]:
        return [_row_to_hardware(r) for r in self._http.records_list(self._table_id)]

    def read(self) -> dict[str, Hardware]:
        """Whole table keyed by ``name``."""
        return {h.name: h for h in self.list_all()}

    def upsert(
        self,
        *,
        name: str,
        device_type: HardwareType,
        kind: Optional[str] = None,
    ) -> Hardware:
        """Create or update a device row, keyed by ``name``."""
        body: dict[str, Any] = {
            HardwareColumns.NAME: name,
            HardwareColumns.TYPE: HardwareType(device_type).value,
            HardwareColumns.KIND: kind,
        }
        try:
            existing: Optional[Hardware] = self.get_by_name(name)
        except NotFoundError:
            existing = None

        if existing is None:
            self._http.records_create(self._table_id, body)
        else:
            self._http.records_update(self._table_id, {HardwareColumns.ID: existing.id, **body})
        return self.get_by_name(name)


def _row_to_hardware(row: dict[str, Any]) -> Hardware:
    return Hardware(
        id=int(row[HardwareColumns.ID]),
        name=str(row[HardwareColumns.NAME]),
        type=HardwareType(str(row[HardwareColumns.TYPE])),
        kind=row.get(HardwareColumns.KIND) or None,
    )
