"""`use_cases` table client — named bundles of services.

One row per use-case, keyed by ``name``; ``services`` is a many-to-many link to the
`services` it bundles. Upsert re-asserts the links idempotently (additive — a seed adds,
never prunes)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from ._base import _BaseTableClient
from ._rows import _resolve_link_displays, _resolve_link_ids
from .errors import NotFoundError
from .schema import ServiceColumns, UseCaseColumns


@dataclass(frozen=True)
class UseCase:
    """One row from the `use_cases` table."""

    id: int
    name: str
    description: Optional[str] = None
    services: list[str] = field(default_factory=list)       # bundled service names
    service_ids: list[int] = field(default_factory=list)    # bundled service ids


class UseCasesClient(_BaseTableClient):
    """Read/write the `use_cases` table."""

    def get_by_name(self, name: str) -> UseCase:
        rows = self._http.records_list(
            self._table_id, where=f"({UseCaseColumns.NAME},eq,{name})", limit=1,
        )
        if not rows:
            raise NotFoundError(f"UseCase with name={name!r} not found")
        return _row_to_use_case(rows[0])

    def list_all(self) -> list[UseCase]:
        return [_row_to_use_case(r) for r in self._http.records_list(self._table_id)]

    def read(self) -> dict[str, UseCase]:
        """Whole table keyed by ``name``."""
        return {u.name: u for u in self.list_all()}

    def upsert(
        self,
        *,
        name: str,
        description: Optional[str] = None,
        service_ids: Optional[list[int]] = None,
    ) -> UseCase:
        """Create or update a use-case row, keyed by ``name``; re-assert its ``services`` links.

        ``service_ids`` are resolved service ids (the caller maps names → ids)."""
        body: dict[str, Any] = {
            UseCaseColumns.NAME: name,
            UseCaseColumns.DESCRIPTION: description,
        }
        try:
            existing: Optional[UseCase] = self.get_by_name(name)
        except NotFoundError:
            existing = None

        if existing is None:
            self._http.records_create(self._table_id, body)
        else:
            self._http.records_update(self._table_id, {UseCaseColumns.ID: existing.id, **body})
        use_case = self.get_by_name(name)
        if service_ids:
            self._link(UseCaseColumns.SERVICES, use_case.id, service_ids)
            use_case = self.get_by_name(name)
        return use_case


def _row_to_use_case(row: dict[str, Any]) -> UseCase:
    return UseCase(
        id=int(row[UseCaseColumns.ID]),
        name=str(row[UseCaseColumns.NAME]),
        description=row.get(UseCaseColumns.DESCRIPTION) or None,
        services=_resolve_link_displays(row.get(UseCaseColumns.SERVICES), ServiceColumns.NAME),
        service_ids=_resolve_link_ids(row.get(UseCaseColumns.SERVICES)),
    )
