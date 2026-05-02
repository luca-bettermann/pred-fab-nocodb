"""Internal base class for table-specific clients."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._http import _HttpClient


class _BaseTableClient:
    """Common state shared by every table-specific client.

    Internal — not part of the public API; clients subclass this for the
    http + base_id wiring.
    """

    def __init__(self, http: "_HttpClient", base_id: str):
        self._http = http
        self._base_id = base_id
