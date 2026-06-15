"""Shared row-field parsers for NocoDB responses.

Single home for the linked-record / datetime normalisers that every table
client needs, so the same logic isn't re-derived (and drifted) per module.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional


def _resolve_link_id(value: Any) -> Optional[int]:
    """NocoDB renders linked-record fields as a list of `{Id: ...}` dicts (or
    a bare int / dict depending on response context). Normalise to int|None.

    Id 0 is treated as "no link" (NocoDB ids start at 1), so it maps to None
    in every branch.
    """
    if value is None or value == "":
        return None
    if isinstance(value, list):
        if not value:
            return None
        first = value[0]
        if isinstance(first, dict):
            return int(first.get("Id", 0)) or None
        return int(first) or None
    if isinstance(value, dict):
        return int(value.get("Id", 0)) or None
    try:
        return int(value) or None
    except (TypeError, ValueError):
        return None


def _resolve_link_code(value: Any) -> Optional[str]:
    """Counterpart to `_resolve_link_id` — extracts the linked record's `code`
    (the LTAR display value) so callers can filter by it. NocoDB v2 LTAR
    filters compare against the display value, not the id."""
    if value is None or value == "":
        return None
    if isinstance(value, list):
        if not value:
            return None
        first = value[0]
        if isinstance(first, dict):
            code = first.get("code")
            return str(code) if code else None
        return None
    if isinstance(value, dict):
        code = value.get("code")
        return str(code) if code else None
    return None


def _parse_dt(value: Any) -> Optional[datetime]:
    """Parse a NocoDB timestamp string to a tz-aware datetime (or None)."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
