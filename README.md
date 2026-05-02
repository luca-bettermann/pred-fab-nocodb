# pred-fab-nocodb

NocoDB binding for the pred-fab data model — typed read/write access to studies, experiments, parameters, features, attributes, and dim_positions.

## Setup

```bash
uv venv
uv sync
```

## Quick start

```python
from pred_fab_nocodb import NocoDBClient, Status

client = NocoDBClient(
    base_url="https://nocodb.example.com",
    api_token="...",
    base_id="...",
)

study = client.studies.get_by_code("ADVEI_2026")
constants = client.study_constants.read(study.id)

exp = client.experiments.create(study_id=study.id, code="ADVEI_2026_001")
client.params.write(
    exp_id=exp.id, exp_code=exp.code,
    value_code="path_offset", value="2.5",
)
client.features.write(
    exp_id=exp.id, exp_code=exp.code,
    value_code="filament_width", value=4.2,
    domain="structural:nodes", axes={"layer_idx": 3, "node_idx": 2},
)
client.experiments.update_status(exp.id, Status.DONE)
```

---

# API reference

## `NocoDBClient`

```python
NocoDBClient(*, base_url: str, api_token: str, base_id: str, timeout: float = 30.0)
```

Public entry point. Resolves NocoDB internal table-IDs at construction; raises `NocoDBError` if any required table is missing from the workspace.

| Attribute | Type | Purpose |
| --- | --- | --- |
| `client.studies` | `StudiesClient` | studies table |
| `client.experiments` | `ExperimentsClient` | experiments table |
| `client.datasets` | `DatasetsClient` | datasets table |
| `client.dim_positions` | `DimPositionsClient` | dim_positions table (with cache) |
| `client.study_constants` | `StudyConstantsClient` | set_study_constants table |
| `client.params` | `ValueClient` | set_exp_params table |
| `client.features` | `ValueClient` | set_exp_features table |
| `client.attributes` | `ValueClient` | set_exp_attributes table |
| `client.workflows` | `WorkflowsClient` | high-level multi-table helpers |

Supports the context-manager protocol; `client.close()` closes the underlying HTTP session.

---

## `StudiesClient`

| Method | Returns | Description |
| --- | --- | --- |
| `get_by_code(code: str)` | `Study` | Fetch by code; `NotFoundError` if absent |
| `list_all()` | `list[Study]` | Every study in the workspace |
| `create(*, code: str, description: str \| None = None)` | `Study` | Create a study row |

### `Study` dataclass

```python
@dataclass(frozen=True)
class Study:
    id: int
    code: str
    description: str | None
    started_at: datetime | None
    ended_at: datetime | None
```

---

## `ExperimentsClient`

| Method | Returns | Description |
| --- | --- | --- |
| `get_by_code(code: str)` | `Experiment` | Fetch by code |
| `list_by_study(study_id: int, *, status: Status \| None = None)` | `list[Experiment]` | All experiments in a study, optionally status-filtered |
| `list_by_dataset(dataset_id: int)` | `list[Experiment]` | All experiments in a dataset |
| `create(*, study_id, code, status=Status.DRAFT, dataset_id=None, notes=None)` | `Experiment` | Create an experiment row |
| `update_status(experiment_id: int, status: Status)` | `None` | Change status |
| `update_timestamps(experiment_id, *, started_at=None, ended_at=None)` | `None` | Set start/end times |
| `set_dataset(experiment_id: int, dataset_id: int \| None)` | `None` | Assign or clear dataset link |

### `Experiment` dataclass

```python
@dataclass(frozen=True)
class Experiment:
    id: int
    code: str
    study_id: int
    status: Status
    dataset_id: int | None
    started_at: datetime | None
    ended_at: datetime | None
    notes: str | None
```

---

## `DatasetsClient`

| Method | Returns | Description |
| --- | --- | --- |
| `get_by_code(code: str)` | `Dataset` | Fetch by code (e.g. `"ADVEI_2026/baseline"`) |
| `list_by_study(study_id: int)` | `list[Dataset]` | All datasets in a study |
| `create(*, study_id, study_code, name, strategy, purpose, description=None)` | `Dataset` | Create. Code auto-generated as `f"{study_code}/{name}"` |

### `Dataset` dataclass

```python
@dataclass(frozen=True)
class Dataset:
    id: int
    code: str
    study_id: int
    name: str
    strategy: Strategy   # how experiments were generated
    purpose: Purpose     # what they're used for
    description: str | None
```

---

## `DimPositionsClient`

| Method | Returns | Description |
| --- | --- | --- |
| `get(position_id: int)` | `DimPosition` | Fetch by NocoDB id |
| `get_by_code(code: str)` | `DimPosition` | Fetch by code, e.g. `"structural:nodes.d2.42"` |
| `find(*, domain, axes)` | `DimPosition \| None` | Look up by `(domain, axes)`; uses cache |
| `list_by_domain(*, domain, depth=None)` | `list[DimPosition]` | All positions in a domain, optionally depth-filtered |
| `get_or_create(*, domain, axes)` | `DimPosition` | Idempotent upsert; auto-generates code with per-`(domain, depth)` counter |
| `get_or_create_batch(*, domain, axes_list)` | `list[DimPosition]` | Bulk upsert; reuses cache |

### `DimPosition` dataclass

```python
@dataclass(frozen=True)
class DimPosition:
    id: int
    code: str            # e.g. "structural:nodes.d2.42"
    domain: str          # e.g. "structural:nodes"
    depth: int           # 0, 1, 2, ...
    axes: dict[str, int]
```

---

## `StudyConstantsClient`

| Method | Returns | Description |
| --- | --- | --- |
| `read(study_id: int)` | `dict[str, float]` | All constants as `{param_code: value}` |
| `get(*, study_id, param_code)` | `float \| None` | Single value, or `None` if absent |
| `write(*, study_id, study_code, param_code, value)` | `None` | Upsert. `study_code` for code generation |
| `delete(*, study_id, param_code)` | `None` | Remove; raises `NotFoundError` if absent |

---

## `ValueClient` (params / features / attributes)

One class, three pre-bound instances on `NocoDBClient`. Every method is the same shape regardless of which value table.

| Method | Returns | Description |
| --- | --- | --- |
| `write(*, exp_id, exp_code, value_code, value, domain=None, axes=None)` | `ValueRow` | Single write. If `axes` is set, `domain` is required; auto-upserts the corresponding `dim_position`. If both are `None`, the row's dim link stays null (per-experiment scope) |
| `write_batch(*, exp_id, exp_code, items: list[ValueWriteItem])` | `list[ValueRow]` | Bulk write; reuses dim-position cache |
| `read(*, exp_id, value_code=None)` | `list[ValueRow]` | All rows for an experiment, optionally filtered by FK code |
| `read_static(exp_id: int)` | `dict[str, Any]` | Per-experiment values (`dim IS NULL`), as `{value_code: value}` |
| `read_trajectory(exp_id: int)` | `dict[str, list[tuple[dict, Any]]]` | Per-position values grouped by code: `{value_code: [(axes, value), ...]}` |

### `ValueRow` dataclass

```python
@dataclass(frozen=True)
class ValueRow:
    id: int
    code: str            # the row's identifying code, e.g. "ADVEI_2026_001/filament_width/structural:nodes.d2.0"
    experiment_id: int
    fk_code: str         # the param/feature/attribute code this row represents
    dim_id: int | None
    value: Any           # str for params, float for features/attributes
```

### `ValueWriteItem` dataclass

```python
@dataclass(frozen=True)
class ValueWriteItem:
    value_code: str                   # the param/feature/attribute code
    value: Any
    domain: str | None = None         # required when axes is non-None
    axes: Mapping[str, int] | None = None   # None ↔ per-experiment scope
```

---

## `WorkflowsClient`

Composed multi-table helpers. Available as `client.workflows`.

### `plan_experiment(...)`

```python
client.workflows.plan_experiment(
    *,
    study_code: str,
    exp_code: str,
    plan: ExperimentPlan,
    dataset_code: str | None = None,
    domain: str | None = None,        # required if plan.trajectory_params is non-empty
) -> int                              # the new experiment id
```

Resolves the study, optionally resolves the dataset, creates a draft experiment, and writes all static + trajectory params in one shot.

```python
@dataclass
class ExperimentPlan:
    static_params: dict[str, Any]
    trajectory_params: dict[str, list[tuple[Mapping[str, int], Any]]]
```

### `load_for_fabrication(...)`

```python
client.workflows.load_for_fabrication(
    *,
    exp_code: str,
    mark_running: bool = True,        # transition DRAFT → RUNNING with timestamp
) -> FabricationLoad
```

Returns everything a fab script needs to run an experiment.

```python
@dataclass(frozen=True)
class FabricationLoad:
    experiment_id: int
    experiment_code: str
    study_id: int
    study_constants: dict[str, float]
    static_params: dict[str, Any]
    trajectory_params: dict[str, list[tuple[dict[str, int], Any]]]
```

### `save_fabrication_result(...)`

```python
client.workflows.save_fabrication_result(
    *,
    exp_code: str,
    status: Status = Status.DONE,
    features: list[ValueWriteItem] | None = None,
    attributes: list[ValueWriteItem] | None = None,
    ended_at: datetime | None = None,
    notes: str | None = None,
) -> None
```

Writes features and attributes in bulk, transitions status, sets `ended_at`.

### `load_dataset(...)`

```python
client.workflows.load_dataset(
    *,
    dataset_code: str,
    only_done: bool = False,          # filter to status=DONE for training
) -> list[ExperimentBundle]
```

Returns one bundle per experiment in the dataset — typically used to build a pred-fab `Dataset`.

```python
@dataclass(frozen=True)
class ExperimentBundle:
    experiment_id: int
    experiment_code: str
    status: Status
    static_params: dict[str, Any]
    trajectory_params: dict[str, list[tuple[dict[str, int], Any]]]
    features: dict[str, list[tuple[dict[str, int], Any]]]
    attributes: dict[str, list[tuple[dict[str, int], Any]]]
```

---

## Enums

```python
class Status(StrEnum):
    DRAFT = "draft"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"

class Strategy(StrEnum):
    """How experiments are generated."""
    GRID = "grid"
    BASELINE = "baseline"
    EXPLORATION = "exploration"
    INFERENCE = "inference"

class Purpose(StrEnum):
    """What experiments are used for."""
    REFERENCE = "reference"
    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"
```

---

## Errors

| Exception | When raised |
| --- | --- |
| `NocoDBError` | Base class; server errors (5xx); JSON parse failures |
| `NotFoundError` | HTTP 404; record / code lookup miss |
| `ConflictError` | HTTP 409; UNIQUE constraint violation |
| `ValidationError` | Other 4xx; malformed request rejected by NocoDB |

All four are exported at package level and are catchable via the base class.

---

## Row-code conventions

| Table | `code` pattern | Example |
| --- | --- | --- |
| `studies` | manual | `"ADVEI_2026"` |
| `experiments` | caller-provided (typically `{study}_{seq}`) | `"ADVEI_2026_001"` |
| `datasets` | `{study_code}/{name}` | `"ADVEI_2026/baseline"` |
| `dim_positions` | `{domain}.d{depth}.{count}` | `"structural:nodes.d2.42"` |
| `set_study_constants` | `{study_code}/{param_code}` | `"ADVEI_2026/conversion_ratio"` |
| `set_exp_params` | `{exp_code}/{param_code}[/{dim_code}]` | `"ADVEI_2026_001/print_speed/structural:nodes.d1.3"` |
| `set_exp_features` | `{exp_code}/{feature_code}/{dim_code}` | `"ADVEI_2026_001/filament_width/structural:nodes.d2.0"` |
| `set_exp_attributes` | `{exp_code}/{attribute_code}/{dim_code}` | `"ADVEI_2026_001/structural_integrity/structural:nodes.d2.0"` |

All codes are generated by the package at write time; consumers pass only the meaningful parts.

---

## Testing

```bash
.venv/bin/pytest tests/unit
.venv/bin/pyright
```

Unit tests use `FakeNocoDBHttp` (in-memory backend in `tests/conftest.py`); no live NocoDB required. Integration tests against a real instance are planned for `tests/integration/` (skip-if-not-configured pattern).

See `PROJECT_CONTEXT.md` for repo layout and design decisions.
