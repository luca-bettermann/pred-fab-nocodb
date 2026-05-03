"""Internal base class for table-specific clients."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .errors import NocoDBError

if TYPE_CHECKING:
    from ._http import _NocoDBHttp


class _BaseTableClient:
    """Common state shared by every table-specific client.

    Internal — not part of the public API; clients subclass this for the
    http + base_id + table_id wiring.

    `table_id` is NocoDB's internal identifier (e.g. `"mxxxxxx"`), resolved
    by `NocoDBClient` at construction via the meta API.

    `link_field_ids` maps the column name of each LTAR field on this table
    (e.g. ``"studies"``) to the NocoDB-internal link-field id. Resolved by
    `NocoDBClient` at construction so subclasses can call ``self._link(...)``
    without re-doing the meta lookup.
    """

    def __init__(
        self,
        http: "_NocoDBHttp",
        base_id: str,
        table_id: str,
        *,
        link_field_ids: dict[str, str] | None = None,
    ):
        self._http = http
        self._base_id = base_id
        self._table_id = table_id
        self._link_field_ids: dict[str, str] = dict(link_field_ids or {})

    def _link(
        self,
        field_name: str,
        record_id: int,
        linked: int | list[int],
    ) -> None:
        """Set a LTAR field via NocoDB's dedicated `/links/` endpoint.

        NocoDB v2's records-create endpoint silently drops link-field values
        from a bulk POST body, so all link writes route through this helper
        to be honoured uniformly (single-record POST inline values do work,
        but going through `/links/` gives one consistent code path).
        """
        link_field_id = self._link_field_ids.get(field_name)
        if link_field_id is None:
            raise NocoDBError(
                f"No link-field id resolved for {field_name!r} on table "
                f"{self._table_id!r}; expected in link_field_ids: "
                f"{sorted(self._link_field_ids)}"
            )
        self._http.link_records(
            table_id=self._table_id,
            link_field_id=link_field_id,
            record_id=record_id,
            linked_record_ids=linked,
        )
