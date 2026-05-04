"""Shared pytest fixtures."""
from __future__ import annotations

from typing import Any, Callable, Optional

import pytest


class FakeNocoDBHttp:
    """In-memory stand-in for `_NocoDBHttp`.

    Recorded calls are available on `.calls` for assertions. Canned responses
    can be registered via `.set_response(method, path_predicate, response)`
    or via `.set_records(table_id, rows)` for a simple in-memory table store
    that supports basic `eq` filters used by the clients.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any] | None, Any]] = []
        # In-memory tables: table_id -> list[row]
        self._tables: dict[str, list[dict[str, Any]]] = {}
        # Override responses keyed by (method, path)
        self._overrides: dict[tuple[str, str], Any] = {}
        self._next_id_per_table: dict[str, int] = {}
        # Per-table column metadata returned by meta_get_table
        self._columns: dict[str, list[dict[str, Any]]] = {}
        # Links recorded via link_records: (table_id, field_id, record_id) -> [linked_ids]
        self._links: dict[tuple[str, str, int], list[int]] = {}
        # Map (table_id, link_field_id) -> column name to mirror onto the row
        self._link_field_to_column: dict[tuple[str, str], str] = {}

    # ─── Test setup helpers ───────────────────────────────────────────

    def set_records(self, table_id: str, rows: list[dict[str, Any]]) -> None:
        """Pre-populate a table with rows. `Id` is auto-assigned if missing."""
        next_id = self._next_id_per_table.get(table_id, 1)
        normalised: list[dict[str, Any]] = []
        for row in rows:
            r = dict(row)
            if "Id" not in r:
                r["Id"] = next_id
                next_id += 1
            normalised.append(r)
        self._tables[table_id] = normalised
        self._next_id_per_table[table_id] = max(next_id, max((r["Id"] for r in normalised), default=0) + 1)

    def get_records(self, table_id: str) -> list[dict[str, Any]]:
        """Read-only snapshot of a table."""
        return list(self._tables.get(table_id, []))

    # ─── Records API ──────────────────────────────────────────────────

    def records_list(
        self,
        table_id: str,
        *,
        where: Optional[str] = None,
        fields: Optional[list[str]] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        sort: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        self.calls.append(("records_list", table_id, {"where": where, "limit": limit}, None))
        rows = self._tables.get(table_id, [])
        filtered = [r for r in rows if _matches_where(r, where)]
        if offset:
            filtered = filtered[offset:]
        if limit is not None:
            filtered = filtered[:limit]
        return filtered

    def records_get(self, table_id: str, record_id: int) -> dict[str, Any]:
        self.calls.append(("records_get", table_id, None, record_id))
        for r in self._tables.get(table_id, []):
            if int(r.get("Id", -1)) == record_id:
                return r
        raise KeyError(f"record_id={record_id} not found in {table_id}")

    def records_create(
        self,
        table_id: str,
        body: dict[str, Any] | list[dict[str, Any]],
    ) -> Any:
        self.calls.append(("records_create", table_id, None, body))
        store = self._tables.setdefault(table_id, [])
        next_id = self._next_id_per_table.get(table_id, 1)
        if isinstance(body, list):
            created: list[dict[str, Any]] = []
            for item in body:
                row = dict(item)
                row.setdefault("Id", next_id)
                next_id += 1
                store.append(row)
                created.append(row)
            self._next_id_per_table[table_id] = next_id
            return created
        row = dict(body)
        row.setdefault("Id", next_id)
        self._next_id_per_table[table_id] = next_id + 1
        store.append(row)
        return row

    def records_update(
        self,
        table_id: str,
        body: dict[str, Any] | list[dict[str, Any]],
    ) -> Any:
        self.calls.append(("records_update", table_id, None, body))
        store = self._tables.get(table_id, [])
        items = body if isinstance(body, list) else [body]
        updated: list[dict[str, Any]] = []
        for item in items:
            target_id = int(item.get("Id", -1))
            for row in store:
                if int(row.get("Id", -2)) == target_id:
                    row.update(item)
                    updated.append(row)
                    break
        return updated if isinstance(body, list) else (updated[0] if updated else {})

    def records_delete(
        self,
        table_id: str,
        body: dict[str, Any] | list[dict[str, Any]],
    ) -> Any:
        self.calls.append(("records_delete", table_id, None, body))
        store = self._tables.get(table_id, [])
        items = body if isinstance(body, list) else [body]
        target_ids = {int(item.get("Id", -1)) for item in items}
        before = len(store)
        self._tables[table_id] = [r for r in store if int(r.get("Id", -2)) not in target_ids]
        return {"deleted": before - len(self._tables[table_id])}

    def records_count(self, table_id: str, *, where: Optional[str] = None) -> int:
        self.calls.append(("records_count", table_id, {"where": where}, None))
        return sum(1 for r in self._tables.get(table_id, []) if _matches_where(r, where))

    # ─── Meta API ─────────────────────────────────────────────────────

    def meta_list_tables(self, base_id: str) -> list[dict[str, Any]]:
        self.calls.append(("meta_list_tables", base_id, None, None))
        # Every table_id we've seen so far is exposed with its name == id (test convention)
        return [{"id": tid, "title": tid} for tid in self._tables.keys()]

    def meta_get_table(self, table_id: str) -> dict[str, Any]:
        """Return seeded column metadata for a table (set via `set_columns`)."""
        self.calls.append(("meta_get_table", table_id, None, None))
        return {
            "id": table_id,
            "title": table_id,
            "columns": list(self._columns.get(table_id, [])),
        }

    def set_columns(self, table_id: str, columns: list[dict[str, Any]]) -> None:
        """Test helper: register column metadata returned by `meta_get_table`."""
        self._columns[table_id] = list(columns)

    # ─── Links API ────────────────────────────────────────────────────

    def link_records(
        self,
        *,
        table_id: str,
        link_field_id: str,
        record_id: int,
        linked_record_ids: int | list[int],
    ) -> None:
        """Record link calls; expose them via `.link_calls` for assertions.

        Also mirror NocoDB's effect: after a link write, subsequent reads of
        the row see the linked record's ``{Id, code}`` dict in the
        corresponding column (NocoDB v2 returns LTAR as a dict, not a bare
        id). Tests register the column-name mapping for a link field via
        ``set_link_field``.
        """
        self.calls.append(("link_records", table_id, {"field": link_field_id, "record": record_id}, linked_record_ids))
        ids = [linked_record_ids] if isinstance(linked_record_ids, int) else list(linked_record_ids)
        self._links.setdefault((table_id, link_field_id, record_id), []).extend(ids)
        # Reflect the link onto the row itself: write a {Id, code} dict (the
        # NocoDB v2 LTAR shape) so reads + filters work correctly.
        column_name = self._link_field_to_column.get((table_id, link_field_id))
        if column_name is not None:
            shaped: list[dict[str, Any]] = [self._shape_link(i) for i in ids]
            for row in self._tables.get(table_id, []):
                if int(row.get("Id", -1)) == record_id:
                    row[column_name] = (
                        shaped[0] if isinstance(linked_record_ids, int) else shaped
                    )
                    break

    def _shape_link(self, linked_id: int) -> dict[str, Any]:
        """Produce the `{Id, code}` LTAR shape by scanning all tables for a
        row with this Id. Falls back to `{Id}` only if no match found."""
        for rows in self._tables.values():
            for row in rows:
                if int(row.get("Id", -1)) == linked_id:
                    code = row.get("code")
                    if code is not None:
                        return {"Id": linked_id, "code": str(code)}
                    return {"Id": linked_id}
        return {"Id": linked_id}

    def set_link_field(self, table_id: str, link_field_id: str, column_name: str) -> None:
        """Register the column name a given link field updates on its row.

        Used by tests so that `link_records` mirrors the real NocoDB effect
        of populating the FK column after a link write.
        """
        self._link_field_to_column[(table_id, link_field_id)] = column_name

    @property
    def link_calls(self) -> list[tuple[str, str, int, list[int]]]:
        """Materialised view: list of (table_id, link_field_id, record_id, [linked_ids])."""
        return [
            (tid, fid, rid, list(linked))
            for (tid, fid, rid), linked in self._links.items()
        ]

    def close(self) -> None:
        pass


# ─── Where-clause evaluator (subset of NocoDB syntax used by clients) ─


def _matches_where(row: dict[str, Any], where: Optional[str]) -> bool:
    """Evaluate a `where` clause of the form `(field,op,value)~and(field,op,value)...`.

    Supports `eq`, `is`, `isnot`, `blank`, `notblank` operators and `~and`
    conjunction. Used only in the fake HTTP fixture to exercise client logic.

    For LTAR fields stored as ``{"Id": ..., "code": ...}``, `eq` matches
    against the linked record's ``code`` (NocoDB v2's LTAR filter
    behaviour); ``blank`` / ``notblank`` are the LTAR-aware null checks
    NocoDB requires (``is,null`` does not work on LTAR fields).
    """
    if not where:
        return True
    parts = where.split("~and")
    for part in parts:
        part = part.strip()
        if not part.startswith("(") or not part.endswith(")"):
            return False
        inner = part[1:-1]
        bits = inner.split(",", 2)
        if len(bits) != 3:
            return False
        field, op, value = bits
        cell = row.get(field)
        if op == "eq":
            if not _eq_matches(cell, value):
                return False
        elif op == "is" and value == "null":
            if not _is_null(cell):
                return False
        elif op == "isnot" and value == "null":
            if _is_null(cell):
                return False
        elif op == "blank":
            if not _is_null(cell):
                return False
        elif op == "notblank":
            if _is_null(cell):
                return False
        else:
            return False
    return True


def _eq_matches(cell: Any, value: str) -> bool:
    if str(cell) == value:
        return True
    if isinstance(cell, (int, float)) and str(cell) == value:
        return True
    if isinstance(cell, dict):
        return _link_matches(cell, value)
    if isinstance(cell, list) and cell:
        return any(_link_matches(item, value) for item in cell if isinstance(item, dict))
    return False


def _link_matches(item: dict[str, Any], value: str) -> bool:
    """LTAR field matches by linked record's `code` (display value).

    Mirrors NocoDB v2 behaviour: LTAR filters compare against the linked
    record's primary value, NOT its id. Tests must seed LTAR cells as
    ``{"Id": ..., "code": ...}`` and pass codes (not ids) to read methods —
    otherwise the test won't catch a real production regression.
    """
    code = item.get("code")
    return code is not None and str(code) == value


def _is_null(cell: Any) -> bool:
    if cell is None or cell == "":
        return True
    if isinstance(cell, list) and not cell:
        return True
    return False


def _link_id(item: Any) -> Any:
    if isinstance(item, dict):
        return item.get("Id", item)
    return item


# ─── Pytest fixtures ──────────────────────────────────────────────────


@pytest.fixture
def fake_http() -> FakeNocoDBHttp:
    """Fresh fake HTTP backend for each test."""
    return FakeNocoDBHttp()


@pytest.fixture
def setup_table(fake_http: FakeNocoDBHttp) -> Callable[..., None]:
    """Helper: register a table id and seed it with rows."""
    def _setup(table_id: str, rows: Optional[list[dict[str, Any]]] = None) -> None:
        fake_http.set_records(table_id, rows or [])
    return _setup
