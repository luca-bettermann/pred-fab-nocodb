"""Shared row-field parsers for NocoDB responses.

Single home for the linked-record / datetime normalisers that every table
client needs, so the same logic isn't re-derived (and drifted) per module.
"""
from __future__ import annotations

import json
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


def _resolve_link_display(value: Any, key: str) -> Optional[str]:
    """Counterpart to `_resolve_link_id` — extract a linked record's display field
    (`key`) so callers can filter by it. NocoDB v2 LTAR filters compare against the
    display value, not the id; `key` is the related table's primary column (`code`
    for code-keyed tables, `name` for `services`/`use_cases`)."""
    if value is None or value == "":
        return None
    if isinstance(value, list):
        if not value:
            return None
        first = value[0]
        if isinstance(first, dict):
            display = first.get(key)
            return str(display) if display else None
        return None
    if isinstance(value, dict):
        display = value.get(key)
        return str(display) if display else None
    return None


def _resolve_link_code(value: Any) -> Optional[str]:
    """`_resolve_link_display` for the common code-keyed tables (experiments, dim_positions)."""
    return _resolve_link_display(value, "code")


def _resolve_link_ids(value: Any) -> list[int]:
    """All linked-record ids from an m2m / has-many LTAR cell (ordered, blanks dropped)."""
    if not isinstance(value, list):
        single = _resolve_link_id(value)
        return [single] if single else []
    ids: list[int] = []
    for item in value:
        if isinstance(item, dict):
            i = int(item.get("Id", 0))
        else:
            try:
                i = int(item)
            except (TypeError, ValueError):
                continue
        if i:
            ids.append(i)
    return ids


def _resolve_link_displays(value: Any, key: str) -> list[str]:
    """All linked-record display values (`key`) from an m2m / has-many LTAR cell."""
    if not isinstance(value, list):
        single = _resolve_link_display(value, key)
        return [single] if single else []
    out: list[str] = []
    for item in value:
        if isinstance(item, dict):
            display = item.get(key)
            if display:
                out.append(str(display))
    return out


def _parse_json(value: Any) -> Any:
    """Deserialize a LongText (JSON) column to its value (dict OR list); None if blank or
    unparseable. An already-parsed dict/list passes through (response-shape robustness)."""
    if value is None or value == "":
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None


def _parse_json_dict(value: Any) -> Optional[dict[str, Any]]:
    """Deserialize a LongText (JSON) column to a dict; None if blank, unparseable, or non-object.

    An already-parsed dict passes through (response-shape robustness)."""
    parsed = _parse_json(value)
    return parsed if isinstance(parsed, dict) else None


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
