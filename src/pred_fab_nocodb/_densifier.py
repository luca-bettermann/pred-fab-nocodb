"""Sparse → dense per-step expansion for trajectory params.

NocoDB stores trajectory params sparsely: a value is recorded only at the
step(s) where it was authored. Fab scripts (rtde-robot-control etc.) need
dense per-step lists — one value at every step in ``[0, n_steps)``. This
module owns the expansion: sort by step, carry the last authored value
forward; backward-fill from the first authored value for steps before it.

Pure stdlib — no pred-fab, no torch.
"""
from __future__ import annotations

from typing import Any

from .errors import ValidationError


def densify(
    sparse: dict[str, list[tuple[dict[str, int], Any]]],
    *,
    dimension: str,
    n_steps: int,
) -> dict[str, list[Any]]:
    """Expand a sparse trajectory dict into one dense list per code.

    Args:
        sparse: ``{param_code: [(axes_dict, value), ...]}``. ``axes_dict``
            must contain ``dimension`` as a key whose value is the step index.
        dimension: The axis along which to densify (e.g. ``"layer_idx"``).
        n_steps: Total number of steps. Each emitted list has this length.

    Returns:
        ``{param_code: [v_0, v_1, ..., v_{n_steps-1}]}``. Codes whose entry
        list is empty are omitted. Steps before the first authored entry
        are backward-filled with that entry's value (the value that was
        active at step 0 is the earliest declared one).

    Raises:
        ValidationError: An entry's axes dict is missing ``dimension``, or
            an entry's step index is outside ``[0, n_steps)``.
    """
    if n_steps <= 0:
        raise ValidationError(f"n_steps must be > 0; got {n_steps}")

    dense: dict[str, list[Any]] = {}
    for code, entries in sparse.items():
        if not entries:
            continue
        ordered = _sort_and_validate(entries, code=code, dimension=dimension, n_steps=n_steps)
        dense[code] = _carry_forward(ordered, n_steps=n_steps)
    return dense


def _sort_and_validate(
    entries: list[tuple[dict[str, int], Any]],
    *,
    code: str,
    dimension: str,
    n_steps: int,
) -> list[tuple[int, Any]]:
    """Validate axes + step bounds, return ``[(step, value), ...]`` sorted by step."""
    extracted: list[tuple[int, Any]] = []
    for axes, value in entries:
        if dimension not in axes:
            raise ValidationError(
                f"trajectory entry for {code!r} is missing dimension {dimension!r} "
                f"in its axes dict {axes!r}"
            )
        step = int(axes[dimension])
        if step < 0 or step >= n_steps:
            raise ValidationError(
                f"trajectory entry for {code!r} has step={step} for dimension "
                f"{dimension!r} but n_steps={n_steps} (valid range [0, {n_steps}))"
            )
        extracted.append((step, value))
    extracted.sort(key=lambda pair: pair[0])
    return extracted


def _carry_forward(
    ordered: list[tuple[int, Any]],
    *,
    n_steps: int,
) -> list[Any]:
    """Build a length-``n_steps`` list by carrying each value forward to the
    next authored step (and backward-filling positions before the first).
    """
    first_value = ordered[0][1]
    out: list[Any] = [first_value] * n_steps
    last_value = first_value
    cursor = 0
    for step, value in ordered:
        for i in range(cursor, step):
            out[i] = last_value
        out[step] = value
        last_value = value
        cursor = step + 1
    for i in range(cursor, n_steps):
        out[i] = last_value
    assert len(out) == n_steps
    return out
