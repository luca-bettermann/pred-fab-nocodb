# pred-fab-nocodb

NocoDB binding for the pred-fab data model — typed read/write access to studies, experiments, datasets, parameters, features, attributes, and dim_positions.

## Setup

```bash
uv venv
uv sync
```

## Quick start

```python
from pred_fab_nocodb import NocoDBClient, Status

client = NocoDBClient(base_url="...", api_token="...", base_id="...")

study = client.studies.get_by_code("ADVEI_2026")
exp = client.experiments.create(study_id=study.id, code="ADVEI_2026_001")
client.params.write(exp_id=exp.id, exp_code=exp.code,
                    value_code="path_offset", value="2.5")
```

---

## API reference

`NocoDBClient(*, base_url, api_token, base_id, timeout=30.0)` — exposes the sub-clients below as attributes.

### `client.studies`

| Method | Description |
|---|---|
| `get_by_code(code)` | Fetch study by code |
| `list_all()` | List all studies |
| `create(*, code, description=None)` | Create a study |

### `client.experiments`

| Method | Description |
|---|---|
| `get_by_code(code)` | Fetch experiment by code |
| `list_by_study(study_id, *, status=None)` | Experiments in a study, optional status filter |
| `list_by_dataset(dataset_id)` | Experiments in a dataset |
| `create(*, study_id, code, status=DRAFT, dataset_id=None, notes=None)` | Create an experiment |
| `update_status(experiment_id, status)` | Change status |
| `update_timestamps(experiment_id, *, started_at=None, ended_at=None)` | Set start/end times |
| `set_dataset(experiment_id, dataset_id)` | Assign or clear dataset link |

### `client.datasets`

| Method | Description |
|---|---|
| `get_by_code(code)` | Fetch dataset by code |
| `list_by_study(study_id)` | All datasets in a study |
| `create(*, study_id, study_code, name, strategy, purpose, description=None)` | Create a dataset |

### `client.dim_positions`

| Method | Description |
|---|---|
| `get(position_id)` | Fetch by id |
| `get_by_code(code)` | Fetch by code |
| `find(*, domain, axes)` | Look up by `(domain, axes)`; returns `None` if absent |
| `list_by_domain(*, domain, depth=None)` | All positions in a domain |
| `get_or_create(*, domain, axes)` | Idempotent upsert; auto-generates code |
| `get_or_create_batch(*, domain, axes_list)` | Bulk upsert |

### `client.study_constants`

| Method | Description |
|---|---|
| `read(study_id)` | All constants as `{param_code: value}` |
| `get(*, study_id, param_code)` | Single value or `None` |
| `write(*, study_id, study_code, param_code, value)` | Upsert |
| `delete(*, study_id, param_code)` | Remove |

### `client.params` / `client.features` / `client.attributes`

Same shape — `ValueClient` parameterised per table.

| Method | Description |
|---|---|
| `write(*, exp_id, exp_code, value_code, value, domain=None, axes=None)` | Single write; auto-upserts dim_position when `axes` is given |
| `write_batch(*, exp_id, exp_code, items)` | Bulk write; reuses dim cache |
| `read(*, exp_id, value_code=None)` | All rows for an experiment |
| `read_static(exp_id)` | Per-experiment values (`dim IS NULL`) as `{code: value}` |
| `read_parameter_updates(exp_id)` | Sparse per-step events as `list[ParameterUpdateEvent]` (params client only) |

### `client.workflows`

| Method | Description |
|---|---|
| `plan_experiment(*, study_code, exp_code, plan, dataset_code=None, domain=None)` | Create draft experiment + write all params in one shot |
| `load_for_fabrication(*, exp_code, mark_running=True)` | Read everything a fab script needs; optionally transitions DRAFT → RUNNING. Returns a `FabricationLoad` with sparse `parameter_updates: list[ParameterUpdateEvent]` — pred-fab's canonical event shape. The consumer projects per-step via `load.as_overrides(schedule_dim="layer_idx")`, which flattens `study_constants` + `static_params` + per-step `{step: value}` dicts (last wins) for `params.update(load.as_overrides(schedule_dim=...))` on the fab-script side. |
| `save_fabrication_result(*, exp_code, status=DONE, features=None, attributes=None, ended_at=None, notes=None)` | Bulk-write features + attributes, transition status |
| `load_dataset(*, dataset_code, only_done=False)` | Bundle all experiments in a dataset for training |
| `purge_dataset(dataset_code)` | Delete a dataset, its experiments, and every per-experiment value row. Idempotent; intended for re-plan flows that need a clean slate. Returns per-table delete counts. |

---

## Enums

- `Status` — `DRAFT`, `RUNNING`, `DONE`, `FAILED`, `CANCELLED`
- `Strategy` — `GRID`, `BASELINE`, `EXPLORATION`, `INFERENCE` (how experiments were generated)
- `Purpose` — `REFERENCE`, `TRAIN`, `VALIDATION`, `TEST` (what they're used for)

## Errors

`NocoDBError` (base) → `NotFoundError`, `ConflictError`, `ValidationError`. All exported at package level.

## Row-code conventions

| Table | Pattern |
|---|---|
| `studies` | manual |
| `experiments` | caller-provided (e.g. `"ADVEI_2026_001"`) |
| `datasets` | `{study_code}/{name}` |
| `dim_positions` | `{domain}.d{depth}.{count}` |
| `set_study_constants` | `{study_code}/{param_code}` |
| `set_exp_params` / `_features` / `_attributes` | `{exp_code}/{value_code}[/{dim_code}]` |

Generated by the package on write; consumers pass only the meaningful parts.

---

## Testing

```bash
.venv/bin/pytest tests/unit
.venv/bin/pyright
```

Unit tests use `FakeNocoDBHttp` in `tests/conftest.py`; no live NocoDB required.

See `PROJECT_CONTEXT.md` for repo layout.
