"""Tests for the config-catalog materialiser (seed → config_params, value-preserving)."""
import json

from pred_fab_nocodb.config_params import ConfigParamsClient, ConfigType
from pred_fab_nocodb.materialise import load_seed, materialise_config_params
from pred_fab_nocodb.schema import ConfigParamColumns


def _client(fake_http):
    return ConfigParamsClient(fake_http, base_id="b1", table_id="config_params")


_SEED = [
    {"code": "fab_speed", "value": 0.05, "type": "real", "scope": "knob",
     "category": "process", "min": 0.0, "max": 0.2, "description": "extrusion speed"},
    {"code": "mode", "value": "clay", "type": "categorical", "options": ["clay", "concrete"]},
    {"code": "dry_run", "value": False, "type": "bool"},
]


def test_materialise_seeds_the_catalog(fake_http):
    c = _client(fake_http)
    n = materialise_config_params(c, _SEED)
    assert n == 3
    catalog = c.read()
    assert set(catalog) == {"fab_speed", "mode", "dry_run"}
    assert catalog["fab_speed"].coerced == 0.05 and catalog["fab_speed"].min == "0.0"
    assert catalog["mode"].options == ["clay", "concrete"]
    assert catalog["dry_run"].coerced is False


def test_materialise_is_value_preserving_on_rerun(fake_http):
    c = _client(fake_http)
    materialise_config_params(c, _SEED)

    # Runtime edit, then re-run the materialiser (the stack-up hook on every `up`).
    row = next(r for r in fake_http.get_records("config_params") if r.get("code") == "fab_speed")
    fake_http.records_update("config_params", {ConfigParamColumns.ID: row["Id"],
                                               ConfigParamColumns.VALUE: "0.11"})
    materialise_config_params(c, _SEED)

    assert c.get_by_code("fab_speed").value == "0.11"          # runtime value preserved
    assert len(fake_http.get_records("config_params")) == 3     # no duplicates


def test_load_seed_accepts_list_and_mapping(tmp_path):
    list_path = tmp_path / "seed.json"
    list_path.write_text(json.dumps(_SEED))
    assert load_seed(str(list_path)) == _SEED

    map_path = tmp_path / "seed_map.json"
    map_path.write_text(json.dumps({"a": {"value": 1, "type": "int"}}))
    assert load_seed(str(map_path)) == [{"code": "a", "value": 1, "type": "int"}]
