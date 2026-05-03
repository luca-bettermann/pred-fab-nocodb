"""Project per-dimension trajectory entries into a per-step sparse dict.

NocoDB stores trajectory params with a generic ``axes`` dict (e.g. for
multi-axis schedules). Fab scripts typically index by a single dimension
(``layer_idx``). This module owns the projection: drop down to one
dimension and key by step index, preserving the sparse shape so consumers
(fimocc et al.) can do their own carry-forward lookup.

Pure stdlib — no pred-fab, no torch.
"""
from __future__ import annotations

from typing import Any

from .errors import ValidationError


def project_to_dimension(
    sparse: dict[str, list[tuple[dict[str, int], Any]]],
    *,
    dimension: str,
) -> dict[str, dict[int, Any]]:
    """Project a generic sparse trajectory dict to a single dimension.

    Args:
        sparse: ``{param_code: [(axes_dict, value), ...]}``. Each entry's
            ``axes_dict`` must contain ``dimension`` as a key.
        dimension: The axis to project onto (e.g. ``"layer_idx"``).

    Returns:
        ``{param_code: {step_index: value, ...}}``. Codes whose entry list
        is empty are omitted. The consumer chooses how to interpret the
        sparse map (carry-forward, interpolate, etc.).

    Raises:
        ValidationError: An entry's axes dict is missing ``dimension``,
            or an entry's step index is negative.
    """
    out: dict[str, dict[int, Any]] = {}
    for code, entries in sparse.items():
        if not entries:
            continue
        out[code] = _project_entries(entries, code=code, dimension=dimension)
    return out


def _project_entries(
    entries: list[tuple[dict[str, int], Any]],
    *,
    code: str,
    dimension: str,
) -> dict[int, Any]:
    projected: dict[int, Any] = {}
    for axes, value in entries:
        if dimension not in axes:
            raise ValidationError(
                f"trajectory entry for {code!r} is missing dimension {dimension!r} "
                f"in its axes dict {axes!r}"
            )
        step = int(axes[dimension])
        if step < 0:
            raise ValidationError(
                f"trajectory entry for {code!r} has negative step={step} "
                f"for dimension {dimension!r}"
            )
        projected[step] = value
    return projected
