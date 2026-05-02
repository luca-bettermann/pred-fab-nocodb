"""Experiments table client."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from ._base import _BaseTableClient
from .schema import Status


@dataclass(frozen=True)
class Experiment:
    """One row from the `experiments` table."""

    id: int
    code: str
    study_id: int
    status: Status
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    notes: Optional[str] = None


class ExperimentsClient(_BaseTableClient):
    """Read/write the `experiments` table."""

    def get_by_code(self, code: str) -> Experiment:
        """Fetch an experiment by its code (e.g. `'exp_001'`)."""
        raise NotImplementedError

    def list_by_study(self, study_id: int) -> list[Experiment]:
        """Return every experiment belonging to a study."""
        raise NotImplementedError

    def create(
        self,
        *,
        study_id: int,
        code: str,
        status: Status = Status.DRAFT,
        notes: Optional[str] = None,
    ) -> Experiment:
        """Create a new experiment row."""
        raise NotImplementedError

    def update_status(self, experiment_id: int, status: Status) -> None:
        """Change an experiment's status."""
        raise NotImplementedError

    def update_timestamps(
        self,
        experiment_id: int,
        *,
        started_at: Optional[datetime] = None,
        ended_at: Optional[datetime] = None,
    ) -> None:
        """Set the start and/or end timestamps. Either argument may be omitted to leave it untouched."""
        raise NotImplementedError
