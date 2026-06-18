"""Schema provisioner — create-if-missing the robolab config catalog (idempotent).

Companion to :mod:`materialise`: provision ensures the *tables/columns/links* exist, then
materialise upserts the *rows*. data-stack's stack-up hook runs ``provision → (rtde seed
export) → materialise`` after NocoDB is healthy, so a fresh box self-provisions on
``docker compose up``.

CLI::  python -m pred_fab_nocodb.provision     (env: NOCODB_URL / NOCODB_API_TOKEN / NOCODB_BASE_ID)

Two passes, both idempotent and safe to re-run every ``up``:
  1. **tables + scalar columns** — create each catalog table if absent, else add only its
     missing scalar columns;
  2. **LTAR links** — add each link column if absent (needs the related tables to exist, so
     it follows pass 1).

⚠️ **Net-new meta-write surface — needs live-NocoDB validation.** The v2 meta-API payloads
here (column ``uidt`` names, SingleSelect ``colOptions``, and especially the **LTAR
``colOptions`` link shape**) are best-effort and unit-tested against the fake only. LTAR
creation — particularly the ``services.requires`` SELF-link — is the part most in need of a
real-API pass; the link body is built in one place (:func:`_ltar_column`) so it can be
adjusted there once validated.
"""
from __future__ import annotations

import os
import sys
from enum import Enum
from typing import Any

from ._http import _NocoDBHttp
from .schema import (
    ConfigParamColumns,
    ConfigScope,
    ConfigType,
    ServiceColumns,
    Tables,
    UnitColumns,
    UseCaseColumns,
)

_P, _S, _U, _UC = ConfigParamColumns, ServiceColumns, UnitColumns, UseCaseColumns


def _text(title: str) -> dict[str, Any]:
    return {"title": title, "uidt": "SingleLineText"}


def _longtext(title: str) -> dict[str, Any]:
    return {"title": title, "uidt": "LongText"}


def _number(title: str) -> dict[str, Any]:
    return {"title": title, "uidt": "Number"}


def _checkbox(title: str) -> dict[str, Any]:
    return {"title": title, "uidt": "Checkbox"}


def _single_select(title: str, enum: type[Enum]) -> dict[str, Any]:
    return {"title": title, "uidt": "SingleSelect",
            "colOptions": {"options": [{"title": m.value} for m in enum]}}


def _ltar_column(title: str, this_table_id: str, related_table_id: str, link_type: str) -> dict[str, Any]:
    """A LinkToAnotherRecord column body for the v2 meta-API (single place to adjust on validation).

    ``link_type`` is ``mm`` (many-to-many), ``hm`` (has-many), or ``bt`` (belongs-to)."""
    return {
        "title": title,
        "uidt": "LinkToAnotherRecord",
        "parentId": this_table_id,
        "childId": related_table_id,
        "type": link_type,
    }


def _scalar_columns() -> dict[str, list[dict[str, Any]]]:
    """Scalar (non-link) column specs per catalog table. LTAR columns are added in pass 2."""
    return {
        Tables.PARAMS: [
            _text(_P.CODE), _text(_P.LABEL),
            _single_select(_P.TYPE, ConfigType), _single_select(_P.SCOPE, ConfigScope),
            _longtext(_P.VALUE), _longtext(_P.OPTIONS),
            _number(_P.MIN), _number(_P.MAX), _text(_P.UNIT), _longtext(_P.DESCRIPTION),
        ],
        Tables.SERVICES: [
            _text(_S.NAME), _checkbox(_S.ENABLED), _text(_S.KIND), _longtext(_S.DASHBOARD),
        ],
        Tables.USE_CASES: [
            _text(_UC.NAME), _longtext(_UC.DESCRIPTION),
        ],
        Tables.UNITS: [
            _text(_U.ROLE), _text(_U.ROBOT), _text(_U.TOOL),
        ],
    }


def _link_specs() -> list[tuple[str, str, str, str]]:
    """LTAR links as ``(table, column, related_table, link_type)``. All target `services`."""
    # All ``mm``: the live base models every link (even logically single ones) as an m2m
    # junction table, and a single-id link write against an m2m relation is the proven path.
    # A param's ``service`` is linked single (one service) over an m2m column.
    return [
        (Tables.SERVICES, _S.REQUIRES, Tables.SERVICES, "mm"),   # self dependency graph
        (Tables.USE_CASES, _UC.SERVICES, Tables.SERVICES, "mm"),
        (Tables.UNITS, _U.SENSORS, Tables.SERVICES, "mm"),
        (Tables.PARAMS, _P.SERVICE, Tables.SERVICES, "mm"),
    ]


def _table_ids(http: _NocoDBHttp, base_id: str) -> dict[str, str]:
    return {t.get("title", ""): t.get("id", "") for t in http.meta_list_tables(base_id)}


def _existing_columns(http: _NocoDBHttp, table_id: str) -> set[str]:
    return {c.get("title", "") for c in http.meta_get_table(table_id).get("columns", [])}


def provision_config_catalog(http: _NocoDBHttp, base_id: str) -> dict[str, Any]:
    """Create-if-missing the four catalog tables, their scalar columns, then their LTAR links.

    Idempotent: returns ``{created_tables, added_columns, added_links}`` describing what changed."""
    created_tables: list[str] = []
    added_columns: dict[str, list[str]] = {}
    added_links: list[str] = []

    # Pass 1 — tables + scalar columns.
    ids = _table_ids(http, base_id)
    for table, spec in _scalar_columns().items():
        tid = ids.get(table)
        if not tid:
            http.meta_create_table(base_id, {"title": table, "columns": spec})
            created_tables.append(table)
            continue
        existing = _existing_columns(http, tid)
        for col in spec:
            if col["title"] not in existing:
                http.meta_create_column(tid, col)
                added_columns.setdefault(table, []).append(col["title"])

    # Pass 2 — LTAR links (related tables now exist).
    ids = _table_ids(http, base_id)
    for table, column, related, link_type in _link_specs():
        tid, rid = ids.get(table), ids.get(related)
        if not tid or not rid:
            continue
        if column not in _existing_columns(http, tid):
            http.meta_create_column(tid, _ltar_column(column, tid, rid, link_type))
            added_links.append(f"{table}.{column}")

    return {"created_tables": created_tables, "added_columns": added_columns, "added_links": added_links}


def main(argv: list[str] | None = None) -> int:
    try:
        url = os.environ["NOCODB_URL"]
        token = os.environ["NOCODB_API_TOKEN"]
        base_id = os.environ["NOCODB_BASE_ID"]
    except KeyError as missing:
        print(f"provision: missing env var {missing}", file=sys.stderr)
        return 2

    http = _NocoDBHttp(base_url=url, api_token=token)
    result = provision_config_catalog(http, base_id)
    print(
        f"provision: created tables {result['created_tables'] or '[]'}; "
        f"added columns {result['added_columns'] or '{}'}; "
        f"added links {result['added_links'] or '[]'}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
