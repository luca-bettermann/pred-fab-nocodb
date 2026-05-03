"""Project per-dimension trajectory entries into a per-step sparse dict."""
from __future__ import annotations

from typing import Any

from .errors import ValidationError


def project_to_dimension(
    sparse: dict[str, list[tuple[dict[str, int], Any]]],
    *,
    dimension: str,
) -> dict[str, dict[int, Any]]:
    """``{code: [(axes, value), ...]}`` → ``{code: {step: value, ...}}``."""
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
