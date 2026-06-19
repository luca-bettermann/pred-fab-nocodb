"""Tests for the config-catalog materialiser — full model end-to-end.

Through provision → link resolution → materialise, exercising the hardware identity table,
the polymorphic param owner (service/hardware/unit), units→hardware composition,
services→hardware, and the scope-aware value authority — the same way the data-stack hook
runs it on stack-up."""
import json

from pred_fab_nocodb.client import _resolve_link_field_ids
from pred_fab_nocodb.config_params import ConfigParamsClient
from pred_fab_nocodb.hardware import HardwareClient
from pred_fab_nocodb.materialise import load_seed, materialise_config_catalog
from pred_fab_nocodb.provision import provision_config_catalog
from pred_fab_nocodb.schema import ConfigParamColumns, Tables
from pred_fab_nocodb.services import ServicesClient
from pred_fab_nocodb.units import UnitsClient
from pred_fab_nocodb.use_cases import UseCasesClient

_CATALOG = (Tables.PARAMS, Tables.SERVICES, Tables.USE_CASES, Tables.UNITS, Tables.HARDWARE)

_SEED = {
    "hardware": [
        {"name": "UR10e", "type": "robot", "kind": "UR10e"},
        {"name": "WASPclay", "type": "tool", "kind": "WASPclay"},
        {"name": "Gocator", "type": "sensor", "kind": "Gocator2530"},
    ],
    "services": [
        {"name": "extruder", "kind": "actuator", "enabled": True},
        {"name": "scan", "kind": "sensor", "requires": ["extruder"],
         "dashboard": [{"kind": "rate", "field": "power_hz", "tab": "scan"}],  # LIST, not dict
         "hardware": "Gocator"},
    ],
    "use_cases": [{"name": "print", "description": "layerwise", "services": ["extruder", "scan"],
                   "set": {"camera.profile": "array"}}],
    "units": [{"role": "printer", "robot": "UR10e", "tool": "WASPclay", "sensors": ["Gocator"]}],
    "params": [
        {"code": "fab_speed", "value": 0.05, "type": "real", "scope": "knob", "service": "extruder"},
        {"code": "flex_deg", "value": 1.5, "type": "real", "scope": "constant", "hardware": "UR10e"},
        {"code": "build_plate", "value": [0, 0], "type": "vector", "scope": "constant", "unit": "printer"},
        {"code": "mode", "value": "clay", "type": "categorical", "options": ["clay", "concrete"]},
    ],
}


def _clients(fake_http):
    """Provision the catalog, resolve link fields, return the five wired clients."""
    provision_config_catalog(fake_http, base_id="b1")
    ids = {t: t for t in _CATALOG}                       # title == id (test convention)
    links, _ = _resolve_link_field_ids(fake_http, ids)
    return {
        "params": ConfigParamsClient(fake_http, "b1", ids[Tables.PARAMS], link_field_ids=links.get(Tables.PARAMS, {})),
        "services": ServicesClient(fake_http, "b1", ids[Tables.SERVICES], link_field_ids=links.get(Tables.SERVICES, {})),
        "use_cases": UseCasesClient(fake_http, "b1", ids[Tables.USE_CASES], link_field_ids=links.get(Tables.USE_CASES, {})),
        "units": UnitsClient(fake_http, "b1", ids[Tables.UNITS], link_field_ids=links.get(Tables.UNITS, {})),
        "hardware": HardwareClient(fake_http, "b1", ids[Tables.HARDWARE], link_field_ids=links.get(Tables.HARDWARE, {})),
    }


def test_materialise_seeds_all_sections_and_links(fake_http):
    cl = _clients(fake_http)
    counts = materialise_config_catalog(seed=_SEED, **cl)
    assert counts == {"hardware": 3, "services": 2, "use_cases": 1, "units": 1, "params": 4}

    # service → its hardware device; dashboard round-trips as a LIST
    scan = cl["services"].get_by_name("scan")
    assert scan.hardware == "Gocator"
    assert scan.dashboard == [{"kind": "rate", "field": "power_hz", "tab": "scan"}]
    # unit composed of hardware devices
    printer = cl["units"].get_by_role("printer")
    assert printer.robot == "UR10e" and printer.tool == "WASPclay" and printer.sensors == ["Gocator"]
    # use-case `set` overrides round-trip
    assert cl["use_cases"].get_by_name("print").overrides == {"camera.profile": "array"}
    # polymorphic param owners resolve to the right (kind, name)
    fab = cl["params"].get_by_code("fab_speed").owner
    assert fab is not None and (fab.kind, fab.name) == ("service", "extruder")
    flex = cl["params"].get_by_code("flex_deg").owner
    assert flex is not None and (flex.kind, flex.name) == ("hardware", "UR10e")
    plate = cl["params"].get_by_code("build_plate").owner
    assert plate is not None and (plate.kind, plate.name) == ("unit", "printer")
    assert cl["params"].get_by_code("mode").owner is None   # global param (no owner)


def test_scope_aware_value_authority_on_rerun(fake_http):
    cl = _clients(fake_http)
    materialise_config_catalog(seed=_SEED, **cl)

    # Runtime edits in NocoDB: a knob value AND a constant value.
    for code, new in [("fab_speed", "0.11"), ("flex_deg", "9.9")]:
        row = next(r for r in fake_http.get_records(Tables.PARAMS) if r.get("code") == code)
        fake_http.records_update(Tables.PARAMS, {ConfigParamColumns.ID: row["Id"], ConfigParamColumns.VALUE: new})
    materialise_config_catalog(seed=_SEED, **cl)   # re-run the stack-up hook

    assert cl["params"].get_by_code("fab_speed").value == "0.11"   # knob: runtime preserved
    assert cl["params"].get_by_code("flex_deg").coerced == 1.5     # constant: seed re-asserted (overwrite)
    assert len(fake_http.get_records(Tables.PARAMS)) == 4          # no duplicates


def test_load_seed_bare_list_is_params(tmp_path):
    path = tmp_path / "seed.json"
    rows = [{"code": "a", "value": 1, "type": "int"}]
    path.write_text(json.dumps(rows))
    assert load_seed(str(path)) == {"params": rows}


def test_load_seed_sectioned(tmp_path):
    path = tmp_path / "seed.json"
    seed = {"hardware": [{"name": "x", "type": "robot"}], "params": [{"code": "a", "value": 1, "type": "int"}]}
    path.write_text(json.dumps(seed))
    assert load_seed(str(path)) == seed
