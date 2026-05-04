"""Sparse parameter-update event — value object shared with pred-fab.

Mirrored here (not imported from pred-fab) so the slim NocoDB binding
stays free of pred-fab's heavy deps (numpy/pandas/matplotlib/torch). The
mirror is intentionally minimal: only the fields and shape needed for
storage round-trip. Consumers that want pred-fab's richer event helpers
(``ParameterTrajectory``, ``events_to_trajectory``, etc.) should depend
on pred-fab directly — pred-fab's ``ParameterUpdateEvent`` is structurally
identical and will deserialize from this one's ``to_dict`` output.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ParameterUpdateEvent:
    """Immutable record of a parameter update at a specific fabrication step.

    A single event bundles every ``(value_code, value)`` pair that changed
    at one ``(dimension, step_index)`` position. Consumers carry-forward
    through unchanged steps.
    """

    updates: dict[str, Any]
    dimension: str | None = None
    step_index: int | None = None
    source_step: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict — round-trip safe with pred-fab's
        ``ParameterUpdateEvent.from_dict``."""
        return {
            "updates": dict(self.updates),
            "dimension": self.dimension,
            "step_index": self.step_index,
            "source_step": self.source_step,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ParameterUpdateEvent:
        return cls(
            updates=dict(data.get("updates", {})),
            dimension=data.get("dimension"),
            step_index=data.get("step_index"),
            source_step=data.get("source_step"),
        )
