"""Schema validator — compares an expected schema dict against the schema
stored in NocoDB's `studies.schema_json` and reports differences.

Used by `NocoDBClient` at construction time when both `study_code` and
`expected_schema` are supplied: if the stored schema diverges from what
the consumer expects, construction raises `SchemaMismatchError` listing
the differences.
"""
from __future__ import annotations

from typing import Any

from .errors import SchemaMismatchError


class SchemaValidator:
    """Stateless utility for diffing two schema dicts."""

    @staticmethod
    def diff(expected: dict[str, Any], actual: dict[str, Any]) -> list[str]:
        """Compare `expected` against `actual`; return a list of human-readable
        difference strings. Empty list ↔ schemas match.

        Compares recursively for dicts; lists/sets compared by membership
        (order-insensitive); scalars compared by equality.
        """
        return _diff_recursive(expected, actual, path="")

    @staticmethod
    def assert_compatible(
        expected: dict[str, Any],
        actual: dict[str, Any] | None,
        *,
        study_code: str,
    ) -> None:
        """Raise `SchemaMismatchError` if `expected` and `actual` differ.

        `actual=None` (no schema stored in NocoDB) is treated as a mismatch:
        the consumer expected a schema but none is published. To bootstrap a
        new study, the consumer should call `studies.push_schema(...)` first.
        """
        if actual is None:
            raise SchemaMismatchError(
                study_code=study_code,
                differences=["studies.schema_json is empty — no schema stored in NocoDB"],
            )
        differences = SchemaValidator.diff(expected, actual)
        if differences:
            raise SchemaMismatchError(study_code=study_code, differences=differences)


def _diff_recursive(
    expected: Any, actual: Any, *, path: str,
) -> list[str]:
    """Recursive diff; returns list of difference descriptions."""
    if isinstance(expected, dict) and isinstance(actual, dict):
        diffs: list[str] = []
        for key in sorted(set(expected) | set(actual)):
            sub_path = f"{path}.{key}" if path else key
            if key not in actual:
                diffs.append(f"{sub_path}: missing in actual (expected {expected[key]!r})")
            elif key not in expected:
                diffs.append(f"{sub_path}: extra in actual (got {actual[key]!r})")
            else:
                diffs.extend(_diff_recursive(expected[key], actual[key], path=sub_path))
        return diffs

    if isinstance(expected, list) and isinstance(actual, list):
        # Order-insensitive comparison via stringified representation
        exp_set = {_freeze(item) for item in expected}
        act_set = {_freeze(item) for item in actual}
        diffs = []
        for missing in sorted(exp_set - act_set):
            diffs.append(f"{path}: list missing item {missing}")
        for extra in sorted(act_set - exp_set):
            diffs.append(f"{path}: list has extra item {extra}")
        return diffs

    if expected != actual:
        return [f"{path}: expected {expected!r}, got {actual!r}"]
    return []


def _freeze(value: Any) -> str:
    """Stable string repr for set membership (handles dicts in lists)."""
    if isinstance(value, dict):
        return "{" + ",".join(f"{k}={_freeze(v)}" for k, v in sorted(value.items())) + "}"
    if isinstance(value, list):
        return "[" + ",".join(_freeze(v) for v in value) + "]"
    return repr(value)
