"""`services` table client — lab capabilities and their dependency graph.

One row per service, keyed by ``name``. ``requires`` is a SELF many-to-many link (a service's
dependencies on other services); ``dashboard`` is a JSON config blob. Upsert is structural
(re-asserts the ``requires`` links idempotently); link *removal* is not synced — a seed only
adds dependencies, never prunes (a catalog is additive)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from ._base import _BaseTableClient
from ._rows import _parse_json_dict, _resolve_link_displays, _resolve_link_ids
from .errors import NotFoundError
from .schema import ServiceColumns


@dataclass(frozen=True)
class Service:
    """One row from the `services` table."""

    id: int
    name: str
    enabled: bool = True
    kind: Optional[str] = None
    requires: list[str] = field(default_factory=list)       # required service names
    requires_ids: list[int] = field(default_factory=list)   # required service ids
    dashboard: Optional[dict[str, Any]] = None


class ServicesClient(_BaseTableClient):
    """Read/write the `services` table (self-`requires` dependency graph)."""

    def get_by_name(self, name: str) -> Service:
        rows = self._http.records_list(
            self._table_id, where=f"({ServiceColumns.NAME},eq,{name})", limit=1,
        )
        if not rows:
            raise NotFoundError(f"Service with name={name!r} not found")
        return _row_to_service(rows[0])

    def list_all(self) -> list[Service]:
        return [_row_to_service(r) for r in self._http.records_list(self._table_id)]

    def read(self) -> dict[str, Service]:
        """Whole table keyed by ``name``."""
        return {s.name: s for s in self.list_all()}

    def upsert(
        self,
        *,
        name: str,
        enabled: bool = True,
        kind: Optional[str] = None,
        dashboard: Optional[dict[str, Any]] = None,
        requires_ids: Optional[list[int]] = None,
    ) -> Service:
        """Create or update a service row, keyed by ``name``; re-assert its ``requires`` links.

        ``requires_ids`` are resolved service ids (the caller maps names → ids); they must
        already exist. Linking is additive/idempotent — re-running does not duplicate."""
        body: dict[str, Any] = {
            ServiceColumns.NAME: name,
            ServiceColumns.ENABLED: enabled,
            ServiceColumns.KIND: kind,
            ServiceColumns.DASHBOARD: json.dumps(dashboard) if dashboard is not None else None,
        }
        try:
            existing: Optional[Service] = self.get_by_name(name)
        except NotFoundError:
            existing = None

        if existing is None:
            self._http.records_create(self._table_id, body)
        else:
            self._http.records_update(self._table_id, {ServiceColumns.ID: existing.id, **body})
        service = self.get_by_name(name)
        if requires_ids:
            self._link(ServiceColumns.REQUIRES, service.id, requires_ids)
            service = self.get_by_name(name)
        return service


def _row_to_service(row: dict[str, Any]) -> Service:
    return Service(
        id=int(row[ServiceColumns.ID]),
        name=str(row[ServiceColumns.NAME]),
        enabled=bool(row.get(ServiceColumns.ENABLED, True)),
        kind=row.get(ServiceColumns.KIND) or None,
        requires=_resolve_link_displays(row.get(ServiceColumns.REQUIRES), ServiceColumns.NAME),
        requires_ids=_resolve_link_ids(row.get(ServiceColumns.REQUIRES)),
        dashboard=_parse_json_dict(row.get(ServiceColumns.DASHBOARD)),
    )
