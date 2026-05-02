"""Public entry point — `NocoDBClient` wires up every typed sub-client."""
from __future__ import annotations

from ._http import _NocoDBHttp
from ._values import ValueClient
from .datasets import DatasetsClient
from .dim_positions import DimPositionsClient
from .errors import NocoDBError
from .experiments import ExperimentsClient
from .schema import (
    AttributeColumns,
    FeatureColumns,
    ParamColumns,
    Tables,
)
from .studies import StudiesClient
from .study_constants import StudyConstantsClient
from .workflows import WorkflowsClient

# Tables we expect to find in the NocoDB workspace at construction time.
_REQUIRED_TABLES = (
    Tables.STUDIES,
    Tables.EXPERIMENTS,
    Tables.DATASETS,
    Tables.DIM_POSITIONS,
    Tables.SET_STUDY_CONSTANTS,
    Tables.SET_EXP_PARAMS,
    Tables.SET_EXP_FEATURES,
    Tables.SET_EXP_ATTRIBUTES,
)


class NocoDBClient:
    """Public entry point. Holds typed sub-clients for each table.

    Construct once per session and share across components that need to
    read or write the same NocoDB workspace.

    On construction, resolves NocoDB internal table-IDs from human-readable
    table names via the meta API, so all subsequent calls use the IDs.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_token: str,
        base_id: str,
        timeout: float = 30.0,
    ):
        self._http = _NocoDBHttp(
            base_url=base_url,
            api_token=api_token,
            timeout=timeout,
        )
        self._base_id = base_id
        self._table_ids = _resolve_table_ids(self._http, base_id)

        # Independent table clients
        self.studies = StudiesClient(
            self._http, base_id, self._table_ids[Tables.STUDIES]
        )
        self.experiments = ExperimentsClient(
            self._http, base_id, self._table_ids[Tables.EXPERIMENTS]
        )
        self.datasets = DatasetsClient(
            self._http, base_id, self._table_ids[Tables.DATASETS]
        )
        self.dim_positions = DimPositionsClient(
            self._http, base_id, self._table_ids[Tables.DIM_POSITIONS]
        )
        self.study_constants = StudyConstantsClient(
            self._http, base_id, self._table_ids[Tables.SET_STUDY_CONSTANTS]
        )

        # Value clients — share `dim_positions` so the cache benefits all writes
        self.params = ValueClient(
            self._http,
            base_id,
            self._table_ids[Tables.SET_EXP_PARAMS],
            fk_code_column=ParamColumns.PARAM,
            dim_client=self.dim_positions,
        )
        self.features = ValueClient(
            self._http,
            base_id,
            self._table_ids[Tables.SET_EXP_FEATURES],
            fk_code_column=FeatureColumns.FEATURE,
            dim_client=self.dim_positions,
        )
        self.attributes = ValueClient(
            self._http,
            base_id,
            self._table_ids[Tables.SET_EXP_ATTRIBUTES],
            fk_code_column=AttributeColumns.ATTRIBUTE,
            dim_client=self.dim_positions,
        )

        # Workflow helpers — composed from the above
        self.workflows = WorkflowsClient(self)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "NocoDBClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _resolve_table_ids(http: _NocoDBHttp, base_id: str) -> dict[str, str]:
    """Resolve table_name → table_id for every required table in the base."""
    tables = http.meta_list_tables(base_id)
    by_name = {t.get("title", ""): t.get("id", "") for t in tables}
    missing = [name for name in _REQUIRED_TABLES if name not in by_name or not by_name[name]]
    if missing:
        raise NocoDBError(
            f"NocoDB base {base_id!r} is missing required tables: {missing}"
        )
    return {name: by_name[name] for name in _REQUIRED_TABLES}
