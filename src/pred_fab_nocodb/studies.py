"""Studies table client."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from ._base import _BaseTableClient


@dataclass(frozen=True)
class Study:
    """One row from the `studies` table."""

    id: int
    code: str
    name: str
    description: Optional[str] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None


class StudiesClient(_BaseTableClient):
    """Read/write the `studies` table."""

    def get_by_code(self, code: str) -> Study:
        """Fetch a study by its code (e.g. `'ADVEI_2026'`). Raises `NotFoundError` if absent."""
        raise NotImplementedError

    def list_all(self) -> list[Study]:
        """Return every study in the workspace."""
        raise NotImplementedError

    def create(
        self,
        *,
        code: str,
        name: str,
        description: Optional[str] = None,
    ) -> Study:
        """Create a new study row."""
        raise NotImplementedError
