"""Schema provisioner — create-if-missing the config catalog tables (idempotent).

Companion to :mod:`materialise`: provision ensures the *tables/columns* exist, then
materialise upserts the *rows*. data-stack's stack-up hook runs ``provision → (rtde seed
export) → materialise`` after NocoDB is healthy, so a fresh box self-provisions on
``docker compose up``.

CLI::  python -m pred_fab_nocodb.provision        (env: NOCODB_URL / NOCODB_API_TOKEN / NOCODB_BASE_ID)

Idempotent: creates the ``config_params`` table if absent; if present, adds only the
columns it is missing. Safe to re-run every ``up``.

⚠️ **Net-new meta-write surface — needs live-NocoDB validation.** The repo has only ever
*read* meta until now; the NocoDB v2 meta-API payloads here (column ``uidt`` names, the
``type`` SingleSelect ``colOptions``) are best-effort and unit-tested against the fake
only. Validate against the stack's real NocoDB on the branch before the consolidated
deploy trusts it. The nested ``rigs`` / ``services`` / ``use_cases`` tables + their LTAR
links are deferred (pending rtde's ``config/*.yaml``); LTAR creation is the part most in
need of real-API validation.
"""
from __future__ import annotations

import os
import sys
from typing import Any

from ._http import _NocoDBHttp
from .config_params import ConfigType
from .schema import ConfigParamColumns, Tables

_C = ConfigParamColumns


def _config_params_columns() -> list[dict[str, Any]]:
    """The `config_params` column spec (NocoDB v2 meta `uidt`s). `type` is a SingleSelect
    over :class:`ConfigType`; the rest are text/long-text. rig/service LTARs are added with
    the nested tables."""
    text = lambda title: {"title": title, "uidt": "SingleLineText"}      # noqa: E731
    longtext = lambda title: {"title": title, "uidt": "LongText"}        # noqa: E731
    return [
        text(_C.CODE),
        longtext(_C.VALUE),
        {"title": _C.TYPE, "uidt": "SingleSelect",
         "colOptions": {"options": [{"title": t.value} for t in ConfigType]}},
        text(_C.SCOPE),
        text(_C.CATEGORY),
        longtext(_C.DESCRIPTION),
        longtext(_C.OPTIONS),
        text(_C.MIN),
        text(_C.MAX),
    ]


def ensure_config_params(http: _NocoDBHttp, base_id: str) -> dict[str, Any]:
    """Create the `config_params` table if missing, else add any missing columns. Idempotent."""
    table_ids = {t.get("title", ""): t.get("id", "") for t in http.meta_list_tables(base_id)}
    spec = _config_params_columns()
    tid = table_ids.get(Tables.CONFIG_PARAMS)

    if not tid:
        http.meta_create_table(base_id, {"title": Tables.CONFIG_PARAMS, "columns": spec})
        return {"created_table": True, "added_columns": [c["title"] for c in spec]}

    existing = {c.get("title", "") for c in http.meta_get_table(tid).get("columns", [])}
    added: list[str] = []
    for col in spec:
        if col["title"] not in existing:
            http.meta_create_column(tid, col)
            added.append(col["title"])
    return {"created_table": False, "added_columns": added}


def main(argv: list[str] | None = None) -> int:
    try:
        url = os.environ["NOCODB_URL"]
        token = os.environ["NOCODB_API_TOKEN"]
        base_id = os.environ["NOCODB_BASE_ID"]
    except KeyError as missing:
        print(f"provision: missing env var {missing}", file=sys.stderr)
        return 2

    http = _NocoDBHttp(base_url=url, api_token=token)
    result = ensure_config_params(http, base_id)
    if result["created_table"]:
        print(f"provision: created {Tables.CONFIG_PARAMS} ({len(result['added_columns'])} columns)")
    elif result["added_columns"]:
        print(f"provision: {Tables.CONFIG_PARAMS} present; added columns {result['added_columns']}")
    else:
        print(f"provision: {Tables.CONFIG_PARAMS} already up to date")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
