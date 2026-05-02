"""Internal base class for table-specific clients."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._http import _NocoDBHttp


class _BaseTableClient:
    """Common state shared by every table-specific client.

    Internal — not part of the public API; clients subclass this for the
    http + base_id + table_id wiring.

    `table_id` is NocoDB's internal identifier (e.g. `"mxxxxxx"`), resolved
    by `NocoDBClient` at construction via the meta API.
    """

    def __init__(self, http: "_NocoDBHttp", base_id: str, table_id: str):
        self._http = http
        self._base_id = base_id
        self._table_id = table_id
