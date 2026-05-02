"""set_study_constants table client."""
from __future__ import annotations

from ._base import _BaseTableClient


class StudyConstantsClient(_BaseTableClient):
    """Read/write per-study constants.

    Constants are conceptually per-study parameters that don't vary across
    experiments — material density, supply voltage, conversion ratios, etc.
    The column holding the constant's identifying code is `param` (so a
    constant is a kind of param).
    """

    def read(self, study_id: int) -> dict[str, float]:
        """Return all constants for a study as `{param_code: value}`."""
        raise NotImplementedError

    def write(
        self,
        *,
        study_id: int,
        study_code: str,
        param_code: str,
        value: float,
    ) -> None:
        """Set a constant value. `study_code` is required for code generation;
        `study_id` is the FK target."""
        raise NotImplementedError

    def delete(self, *, study_id: int, param_code: str) -> None:
        """Remove a constant."""
        raise NotImplementedError
