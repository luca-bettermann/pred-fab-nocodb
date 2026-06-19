"""Config-catalog materialiser — seed the robolab config catalog from a repo seed.

Run at stack-up (after NocoDB is healthy) to bring the catalog into line with the deployed
config seed. **Scope-aware** for params (delegates to ``ConfigParamsClient.upsert``): tunable
values (`knob`/`editable`) are preserved across re-runs, `constant`/`safety` re-seed
overwrites. **Seed-agnostic** — it consumes a *normalised* seed; the producing service (rtde)
maps its ``config/*.yaml`` to this shape.

CLI (one-shot; the data-stack compose runs it after NocoDB is healthy)::

    python -m pred_fab_nocodb.materialise --seed <path.json>

The seed is **JSON** with optional sections ``hardware`` / ``services`` / ``use_cases`` /
``units`` / ``params`` (a bare list is taken as ``params``). Cross-table references are by
**name** (services/hardware) or **role** (units), resolved to ids here; sections are
materialised in dependency order (``hardware`` → ``services`` → ``use_cases`` → ``units`` →
``params``) so links resolve:

    {"hardware":   [{"name": "UR10e", "type": "robot", "kind": "UR10e"}],
     "services":   [{"name": "...", "enabled": true, "kind": "...", "dashboard": {...},
                     "requires": ["..."], "hardware": "Gocator"}],
     "use_cases":  [{"name": "...", "description": "...", "services": ["..."]}],
     "units":      [{"role": "printer", "robot": "UR10e", "tool": "WASPclay",
                     "sensors": ["Gocator"]}],
     "params":     [{"code": "...", "value": ..., "type": "real", "scope": "knob",
                     "options": [...], "min": ..., "max": ..., "unit": "...",
                     "service": "..." | "hardware": "..." | "unit": "printer"}]}

A param carries **at most one** owner key (`service`/`hardware`/`unit`); 2+ fails loud.
Env: ``NOCODB_URL``, ``NOCODB_API_TOKEN``, ``NOCODB_ROBOLAB_BASE_ID``. Exit 0 on success, 2 if
the catalog tables aren't provisioned (run :mod:`provision` first).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from ._http import _NocoDBHttp
from .client import _resolve_link_field_ids
from .config_params import ConfigParamsClient
from .hardware import HardwareClient
from .schema import ConfigType, HardwareType, Tables
from .services import ServicesClient
from .units import UnitsClient
from .use_cases import UseCasesClient

_CATALOG_TABLES = (
    Tables.PARAMS, Tables.SERVICES, Tables.USE_CASES, Tables.UNITS, Tables.HARDWARE,
)


def materialise_config_catalog(
    *,
    params: ConfigParamsClient,
    services: ServicesClient,
    use_cases: UseCasesClient,
    units: UnitsClient,
    hardware: HardwareClient,
    seed: dict[str, list[dict[str, Any]]],
) -> dict[str, int]:
    """Upsert every seed section in dependency order; returns per-section row counts.

    ``hardware`` first (devices are the link-target), then ``services`` (two sub-passes: create
    all, then link ``requires``/``hardware`` once everything exists), then ``use_cases`` /
    ``units`` / ``params`` resolving their name/role references."""
    hw_rows = seed.get("hardware", [])
    svc_rows = seed.get("services", [])
    uc_rows = seed.get("use_cases", [])
    unit_rows = seed.get("units", [])
    param_rows = seed.get("params", [])

    hardware_ids: dict[str, int] = {}
    for h in hw_rows:
        rec = hardware.upsert(name=h["name"], device_type=HardwareType(h["type"]), kind=h.get("kind"))
        hardware_ids[rec.name] = rec.id

    service_ids: dict[str, int] = {}
    for s in svc_rows:
        rec = services.upsert(
            name=s["name"], enabled=s.get("enabled", True),
            kind=s.get("kind"), dashboard=s.get("dashboard"),
        )
        service_ids[rec.name] = rec.id
    for s in svc_rows:
        requires = [service_ids[r] for r in s.get("requires", []) if r in service_ids]
        hw_name = s.get("hardware")
        hw_id = hardware_ids.get(hw_name) if hw_name else None
        if requires or hw_id is not None:
            services.upsert(
                name=s["name"], enabled=s.get("enabled", True),
                kind=s.get("kind"), dashboard=s.get("dashboard"),
                requires_ids=requires or None, hardware_id=hw_id,
            )

    for u in uc_rows:
        sids = [service_ids[n] for n in u.get("services", []) if n in service_ids]
        use_cases.upsert(name=u["name"], description=u.get("description"), service_ids=sids or None)

    unit_ids: dict[str, int] = {}
    for u in unit_rows:
        sids = [hardware_ids[n] for n in u.get("sensors", []) if n in hardware_ids]
        rec = units.upsert(
            role=u["role"],
            robot_id=hardware_ids.get(u["robot"]) if u.get("robot") else None,
            tool_id=hardware_ids.get(u["tool"]) if u.get("tool") else None,
            sensor_ids=sids or None,
        )
        unit_ids[rec.role] = rec.id

    for p in param_rows:
        params.upsert(
            code=p["code"], value=p.get("value"), value_type=ConfigType(p["type"]),
            label=p.get("label"), scope=p.get("scope"), description=p.get("description"),
            options=p.get("options"), min=p.get("min"), max=p.get("max"), unit=p.get("unit"),
            service_id=service_ids.get(p["service"]) if p.get("service") else None,
            hardware_id=hardware_ids.get(p["hardware"]) if p.get("hardware") else None,
            unit_id=unit_ids.get(p["unit"]) if p.get("unit") else None,
        )

    return {
        "hardware": len(hw_rows), "services": len(svc_rows), "use_cases": len(uc_rows),
        "units": len(unit_rows), "params": len(param_rows),
    }


def load_seed(path: str) -> dict[str, list[dict[str, Any]]]:
    """Load a normalised JSON seed → sectioned dict (a bare list is taken as ``params``)."""
    data = json.loads(Path(path).read_text())
    if isinstance(data, list):
        return {"params": list(data)}
    return {section: list(rows) for section, rows in data.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pred_fab_nocodb.materialise", description=__doc__)
    parser.add_argument("--seed", required=True, help="path to the normalised config seed (.json)")
    args = parser.parse_args(argv)

    try:
        url = os.environ["NOCODB_URL"]
        token = os.environ["NOCODB_API_TOKEN"]
        base_id = os.environ["NOCODB_ROBOLAB_BASE_ID"]
    except KeyError as missing:
        print(f"materialise: missing env var {missing}", file=sys.stderr)
        return 2

    http = _NocoDBHttp(base_url=url, api_token=token)
    table_ids = {t.get("title", ""): t.get("id", "") for t in http.meta_list_tables(base_id)}
    missing = [t for t in _CATALOG_TABLES if not table_ids.get(t)]
    if missing:
        print(f"materialise: catalog tables {missing} not provisioned in base {base_id}", file=sys.stderr)
        return 2

    cat_ids = {t: table_ids[t] for t in _CATALOG_TABLES}
    links, _ = _resolve_link_field_ids(http, cat_ids)
    counts = materialise_config_catalog(
        params=ConfigParamsClient(http, base_id, cat_ids[Tables.PARAMS],
                                  link_field_ids=links.get(Tables.PARAMS, {})),
        services=ServicesClient(http, base_id, cat_ids[Tables.SERVICES],
                                link_field_ids=links.get(Tables.SERVICES, {})),
        use_cases=UseCasesClient(http, base_id, cat_ids[Tables.USE_CASES],
                                 link_field_ids=links.get(Tables.USE_CASES, {})),
        units=UnitsClient(http, base_id, cat_ids[Tables.UNITS],
                          link_field_ids=links.get(Tables.UNITS, {})),
        hardware=HardwareClient(http, base_id, cat_ids[Tables.HARDWARE],
                                link_field_ids=links.get(Tables.HARDWARE, {})),
        seed=load_seed(args.seed),
    )
    print("materialised " + ", ".join(f"{n} {k}" for k, n in counts.items()))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
