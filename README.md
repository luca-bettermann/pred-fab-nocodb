# pred-fab-nocodb

NocoDB binding for the pred-fab data model — typed read/write access to studies, experiments, parameters, features, attributes, and dim_positions.

## Setup

```bash
uv venv
uv sync
```

## Usage

```python
from pred_fab_nocodb import NocoDBClient, Status

client = NocoDBClient(
    base_url="https://nocodb.example.com",
    api_token="...",
    base_id="...",
)

# Read study + constants
study = client.studies.get_by_code("ADVEI_2026")
constants = client.study_constants.read(study.id)

# Create experiment, write values
exp = client.experiments.create(study_id=study.id, code="exp_001", status=Status.DRAFT)
client.params.write(exp_id=exp.id, code="path_offset", value=2.5)
client.params.write(
    exp_id=exp.id, code="print_speed", value=0.005,
    domain="structural:nodes", axes={"layer_idx": 3},
)
client.features.write(
    exp_id=exp.id, code="filament_width", value=4.2,
    domain="structural:nodes", axes={"layer_idx": 3, "node_idx": 2},
)
client.experiments.update_status(exp.id, Status.DONE)
```

See `PROJECT_CONTEXT.md` for repo layout.
