"""Tests for the config-catalog materialiser (sectioned seed → catalog, value-preserving).

End-to-end through provision → link resolution → materialise, so the LTAR wiring
(services.requires self-link, use_case→services, unit→sensors, param→service) is exercised
against the fake the same way the data-stack hook runs it on stack-up."""
import json

from pred_fab_nocodb.client import _resolve_link_field_ids
from pred_fab_nocodb.config_params import ConfigParamsClient
from pred_fab_nocodb.materialise import load_seed, materialise_config_catalog
from pred_fab_nocodb.provision import provision_config_catalog
from pred_fab_nocodb.schema import ConfigParamColumns, Tables
from pred_fab_nocodb.services import ServicesClient
from pred_fab_nocodb.units import UnitsClient
from pred_fab_nocodb.use_cases import UseCasesClient

_CATALOG = (Tables.PARAMS, Tables.SERVICES, Tables.USE_CASES, Tables.UNITS)

_SEED = {
    "services": [
        {"name": "extruder", "kind": "actuator", "enabled": True},
        {"name": "camera", "kind": "sensor", "requires": ["extruder"], "dashboard": {"panel": "cam"}},
    ],
    "use_cases": [{"name": "print", "description": "layerwise", "services": ["extruder", "camera"]}],
    "units": [{"role": "printer", "robot": "UR10e", "tool": "wasp", "sensors": ["camera"]}],
    "params": [
        {"code": "fab_speed", "value": 0.05, "type": "real", "scope": "knob", "service": "extruder"},
        {"code": "mode", "value": "clay", "type": "categorical", "options": ["clay", "concrete"]},
    ],
}


def _clients(fake_http):
    """Provision the catalog, resolve link fields, return the four wired clients."""
    provision_config_catalog(fake_http, base_id="b1")
    ids = {t: t for t in _CATALOG}                       # title == id (test convention)
    links, _ = _resolve_link_field_ids(fake_http, ids)
    return {
        "params": ConfigParamsClient(fake_http, "b1", ids[Tables.PARAMS], link_field_ids=links.get(Tables.PARAMS, {})),
        "services": ServicesClient(fake_http, "b1", ids[Tables.SERVICES], link_field_ids=links.get(Tables.SERVICES, {})),
        "use_cases": UseCasesClient(fake_http, "b1", ids[Tables.USE_CASES], link_field_ids=links.get(Tables.USE_CASES, {})),
        "units": UnitsClient(fake_http, "b1", ids[Tables.UNITS], link_field_ids=links.get(Tables.UNITS, {})),
    }


def test_materialise_seeds_all_sections_and_links(fake_http):
    cl = _clients(fake_http)
    counts = materialise_config_catalog(seed=_SEED, **cl)
    assert counts == {"services": 2, "use_cases": 1, "units": 1, "params": 2}

    cam = cl["services"].get_by_name("camera")
    assert cam.kind == "sensor" and cam.requires == ["extruder"] and cam.dashboard == {"panel": "cam"}
    assert set(cl["use_cases"].get_by_name("print").services) == {"extruder", "camera"}
    assert cl["units"].get_by_role("printer").sensors == ["camera"]
    fab = cl["params"].get_by_code("fab_speed")
    assert fab.service == "extruder" and fab.coerced == 0.05
    assert cl["params"].get_by_code("mode").options == ["clay", "concrete"]


def test_materialise_value_preserving_on_rerun(fake_http):
    cl = _clients(fake_http)
    materialise_config_catalog(seed=_SEED, **cl)

    # Runtime edit of a param value, then re-run the materialiser (the every-`up` hook).
    row = next(r for r in fake_http.get_records(Tables.PARAMS) if r.get("code") == "fab_speed")
    fake_http.records_update(Tables.PARAMS, {ConfigParamColumns.ID: row["Id"],
                                             ConfigParamColumns.VALUE: "0.11"})
    materialise_config_catalog(seed=_SEED, **cl)

    assert cl["params"].get_by_code("fab_speed").value == "0.11"   # runtime value preserved
    assert len(fake_http.get_records(Tables.PARAMS)) == 2          # no duplicates


def test_load_seed_bare_list_is_params(tmp_path):
    path = tmp_path / "seed.json"
    rows = [{"code": "a", "value": 1, "type": "int"}]
    path.write_text(json.dumps(rows))
    assert load_seed(str(path)) == {"params": rows}


def test_load_seed_sectioned(tmp_path):
    path = tmp_path / "seed.json"
    seed = {"services": [{"name": "x"}], "params": [{"code": "a", "value": 1, "type": "int"}]}
    path.write_text(json.dumps(seed))
    assert load_seed(str(path)) == seed
