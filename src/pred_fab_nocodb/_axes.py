"""Axes canonicalisation.

The contract for `dim_positions.UNIQUE(domain, axes)`: serialise axes to a
canonical JSON form (sorted keys, no whitespace) before insert. This
guarantees that `{"a": 1, "b": 2}` and `{"b": 2, "a": 1}` are recognised
as the same position.
"""
from __future__ import annotations

import json
from typing import Mapping


def canonicalize_axes(axes: Mapping[str, int]) -> str:
    """Canonical JSON serialisation of axes — sorted keys, no whitespace.

    Used as the database contract for `UNIQUE(domain, axes)` and as a
    stable cache key in `DimPositionsClient`.
    """
    sorted_axes = {k: int(v) for k, v in sorted(axes.items())}
    return json.dumps(sorted_axes, separators=(",", ":"))
