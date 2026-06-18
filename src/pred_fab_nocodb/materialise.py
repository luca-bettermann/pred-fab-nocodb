"""Config-catalog materialiser — seed the `config_params` catalog from a repo seed.

Run at stack-up (after NocoDB is healthy) to bring the catalog into line with the
deployed config seed. Idempotent and **value-preserving** (delegates to
``ConfigParamsClient.upsert``): re-running refreshes structural metadata but never
clobbers a runtime-edited value. **Seed-agnostic** — it consumes a *normalised* seed (a
list of param dicts, or a ``code → fields`` mapping); the producing service (rtde) maps
its ``config/*.yaml`` to that shape, so this materialiser never couples to rtde's config
format.

CLI (one-shot; the data-stack compose runs it after NocoDB is healthy)::

    python -m pred_fab_nocodb.materialise --seed <path.json>

The seed is **JSON** — a normalised export the producing service (rtde) generates from its
``config/*.yaml`` (rtde already parses its own YAML; emitting JSON keeps this binding slim
and seed-format-agnostic). Env: ``NOCODB_URL``, ``NOCODB_API_TOKEN``, ``NOCODB_BASE_ID``. Exit 0 on success,
2 if the ``config_params`` table isn't provisioned in the base. Assumes the table
exists (row materialiser, not a table-creator — provisioning the columns is a separate
NocoDB-admin step).

Seed row fields (all but ``code``/``value``/``type`` optional): ``code``, ``value``
(the seed default — written only on first creation), ``type`` (a :class:`ConfigType`
value), ``scope``, ``category``, ``description``, ``options`` (list), ``min``, ``max``.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from ._http import _NocoDBHttp
from .config_params import ConfigParamsClient, ConfigType
from .schema import Tables


def materialise_config_params(client: ConfigParamsClient, seed: list[dict[str, Any]]) -> int:
    """Value-preserving upsert of each seed row into the catalog; returns the row count."""
    for row in seed:
        client.upsert(
            code=row["code"],
            value=row.get("value"),
            value_type=ConfigType(row["type"]),
            scope=row.get("scope"),
            category=row.get("category"),
            description=row.get("description"),
            options=row.get("options"),
            min=row.get("min"),
            max=row.get("max"),
        )
    return len(seed)


def load_seed(path: str) -> list[dict[str, Any]]:
    """Load a normalised JSON seed file → list of param dicts (accepts a list or a code→fields map)."""
    data = json.loads(Path(path).read_text())
    if isinstance(data, dict):
        return [{"code": code, **fields} for code, fields in data.items()]
    return list(data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pred_fab_nocodb.materialise", description=__doc__)
    parser.add_argument("--seed", required=True, help="path to the normalised config seed (.json/.yaml)")
    args = parser.parse_args(argv)

    try:
        url = os.environ["NOCODB_URL"]
        token = os.environ["NOCODB_API_TOKEN"]
        base_id = os.environ["NOCODB_BASE_ID"]
    except KeyError as missing:
        print(f"materialise: missing env var {missing}", file=sys.stderr)
        return 2

    http = _NocoDBHttp(base_url=url, api_token=token)
    table_ids = {t.get("title", ""): t.get("id", "") for t in http.meta_list_tables(base_id)}
    cp_id = table_ids.get(Tables.CONFIG_PARAMS)
    if not cp_id:
        print(f"materialise: table {Tables.CONFIG_PARAMS!r} not provisioned in base {base_id}", file=sys.stderr)
        return 2

    client = ConfigParamsClient(http, base_id, cp_id)
    seed = load_seed(args.seed)
    count = materialise_config_params(client, seed)
    print(f"materialised {count} config params into {Tables.CONFIG_PARAMS}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
